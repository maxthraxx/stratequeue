"""
IB Gateway Data Manager

Data manager for handling streaming data from IB Gateway broker.
Provides a clean interface for strategies to subscribe to and receive real-time market data.
"""

import logging
import pandas as pd
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Callable
from threading import Lock
import time

logger = logging.getLogger(__name__)


class IBDataManager:
    """
    Data manager for IB Gateway streaming data
    
    Provides centralized management of real-time data subscriptions,
    data buffering, and strategy callbacks for IB Gateway broker.
    """
    
    def __init__(self, broker):
        """
        Initialize data manager
        
        Args:
            broker: IBGatewayBroker instance
        """
        self.broker = broker
        self.data_buffer = {}  # symbol -> list of data points
        self.subscribers = {}  # symbol -> list of callback functions
        self.subscription_types = {}  # symbol -> subscription type ('market_data', 'bars', 'both')
        self.data_lock = Lock()  # Thread safety for data operations
        
        # Configuration
        self.max_buffer_size = 1000
        self.buffer_cleanup_interval = 300  # 5 minutes
        self.last_cleanup = time.time()
        
        logger.info("IB Data Manager initialized")
    
    def subscribe_to_symbol(self, symbol: str, callback: Callable, subscription_type: str = 'both') -> bool:
        """
        Subscribe to real-time data for a symbol
        
        Args:
            symbol: Symbol to subscribe to
            callback: Function to call when new data arrives
            subscription_type: Type of subscription ('market_data', 'bars', 'both')
            
        Returns:
            True if subscription successful
        """
        if not self.broker.is_connected:
            logger.error("Broker not connected - cannot subscribe to data")
            return False
        
        with self.data_lock:
            # Store callback
            if symbol not in self.subscribers:
                self.subscribers[symbol] = []
            self.subscribers[symbol].append(callback)
            
            # Store subscription type
            self.subscription_types[symbol] = subscription_type
            
            # Initialize data buffer
            if symbol not in self.data_buffer:
                self.data_buffer[symbol] = []
        
        # Create internal callback that updates our buffer
        def internal_callback(data_type: str, data: Dict):
            """Handle incoming data from broker"""
            try:
                # Add metadata
                enhanced_data = data.copy()
                enhanced_data.update({
                    'symbol': symbol,
                    'data_type': data_type,
                    'received_at': datetime.now()
                })
                
                # Update buffer
                self._update_buffer(symbol, enhanced_data)
                
                # Call strategy callbacks
                for callback_func in self.subscribers.get(symbol, []):
                    try:
                        callback_func(symbol, data_type, enhanced_data)
                    except Exception as e:
                        logger.error(f"Error in strategy callback for {symbol}: {e}")
                
            except Exception as e:
                logger.error(f"Error processing data for {symbol}: {e}")
        
        # Subscribe to broker data based on type
        success = True
        if subscription_type in ['market_data', 'both']:
            success &= self.broker.subscribe_market_data(symbol, internal_callback)
        
        if subscription_type in ['bars', 'both']:
            success &= self.broker.subscribe_real_time_bars(symbol, 5, internal_callback)  # 5-second bars
        
        if success:
            logger.info(f"📊 Subscribed to {subscription_type} for {symbol}")
        else:
            logger.error(f"❌ Failed to subscribe to {subscription_type} for {symbol}")
        
        return success
    
    def unsubscribe_from_symbol(self, symbol: str, callback: Callable = None) -> bool:
        """
        Unsubscribe from data for a symbol
        
        Args:
            symbol: Symbol to unsubscribe from
            callback: Specific callback to remove (if None, removes all)
            
        Returns:
            True if unsubscription successful
        """
        with self.data_lock:
            if symbol not in self.subscribers:
                logger.warning(f"No subscriptions found for {symbol}")
                return False
            
            if callback:
                # Remove specific callback
                if callback in self.subscribers[symbol]:
                    self.subscribers[symbol].remove(callback)
                    logger.info(f"Removed callback for {symbol}")
                    
                    # If no more callbacks, clean up
                    if not self.subscribers[symbol]:
                        del self.subscribers[symbol]
                        if symbol in self.subscription_types:
                            del self.subscription_types[symbol]
                        logger.info(f"All callbacks removed for {symbol}")
                        return True
            else:
                # Remove all callbacks for symbol
                del self.subscribers[symbol]
                if symbol in self.subscription_types:
                    del self.subscription_types[symbol]
                logger.info(f"All subscriptions removed for {symbol}")
        
        return True
    
    def get_latest_data(self, symbol: str, data_type: str = None) -> Optional[Dict]:
        """
        Get latest data for symbol
        
        Args:
            symbol: Symbol to get data for
            data_type: Filter by data type ('tick', 'bar', None for any)
            
        Returns:
            Latest data point or None
        """
        with self.data_lock:
            if symbol not in self.data_buffer or not self.data_buffer[symbol]:
                return None
            
            # Filter by data type if specified
            if data_type:
                for data_point in reversed(self.data_buffer[symbol]):
                    if data_point.get('data_type') == data_type:
                        return data_point
                return None
            else:
                return self.data_buffer[symbol][-1]
    
    def get_historical_buffer(self, symbol: str, count: int = 100, data_type: str = None) -> List[Dict]:
        """
        Get historical data buffer for symbol
        
        Args:
            symbol: Symbol to get buffer for
            count: Number of data points to return
            data_type: Filter by data type ('tick', 'bar', None for any)
            
        Returns:
            List of data points
        """
        with self.data_lock:
            if symbol not in self.data_buffer:
                return []
            
            buffer = self.data_buffer[symbol]
            
            # Filter by data type if specified
            if data_type:
                buffer = [dp for dp in buffer if dp.get('data_type') == data_type]
            
            return buffer[-count:]
    
    def get_price_series(self, symbol: str, count: int = 100) -> pd.Series:
        """
        Get price series as pandas Series
        
        Args:
            symbol: Symbol to get prices for
            count: Number of price points to return
            
        Returns:
            Pandas Series with prices and timestamps
        """
        buffer = self.get_historical_buffer(symbol, count)
        
        if not buffer:
            return pd.Series(dtype=float)
        
        # Extract prices and timestamps
        prices = []
        timestamps = []
        
        for data_point in buffer:
            if 'last_price' in data_point and data_point['last_price'] is not None:
                prices.append(data_point['last_price'])
                timestamps.append(data_point.get('received_at', datetime.now()))
            elif 'close' in data_point:  # Bar data
                prices.append(data_point['close'])
                timestamps.append(data_point.get('datetime', data_point.get('received_at', datetime.now())))
        
        if prices:
            return pd.Series(prices, index=timestamps)
        else:
            return pd.Series(dtype=float)
    
    def get_ohlcv_dataframe(self, symbol: str, count: int = 100) -> pd.DataFrame:
        """
        Get OHLCV data as pandas DataFrame
        
        Args:
            symbol: Symbol to get OHLCV for
            count: Number of bars to return
            
        Returns:
            DataFrame with OHLCV data
        """
        # Get bar data only
        buffer = self.get_historical_buffer(symbol, count, data_type='bar')
        
        if not buffer:
            return pd.DataFrame()
        
        # Convert to DataFrame
        df_data = []
        for data_point in buffer:
            if all(key in data_point for key in ['open', 'high', 'low', 'close']):
                df_data.append({
                    'datetime': data_point.get('datetime', data_point.get('received_at')),
                    'open': data_point['open'],
                    'high': data_point['high'],
                    'low': data_point['low'],
                    'close': data_point['close'],
                    'volume': data_point.get('volume', 0)
                })
        
        if df_data:
            df = pd.DataFrame(df_data)
            df['datetime'] = pd.to_datetime(df['datetime'])
            df.set_index('datetime', inplace=True)
            return df
        else:
            return pd.DataFrame()
    
    def get_subscribed_symbols(self) -> List[str]:
        """Get list of currently subscribed symbols"""
        with self.data_lock:
            return list(self.subscribers.keys())
    
    def get_subscription_info(self) -> Dict[str, Dict]:
        """
        Get detailed subscription information
        
        Returns:
            Dictionary with subscription details for each symbol
        """
        with self.data_lock:
            info = {}
            for symbol in self.subscribers:
                info[symbol] = {
                    'symbol': symbol,
                    'subscription_type': self.subscription_types.get(symbol, 'unknown'),
                    'callback_count': len(self.subscribers[symbol]),
                    'buffer_size': len(self.data_buffer.get(symbol, [])),
                    'latest_data': self.get_latest_data(symbol)
                }
            return info
    
    def _update_buffer(self, symbol: str, data: Dict):
        """Update data buffer for symbol (thread-safe)"""
        with self.data_lock:
            if symbol not in self.data_buffer:
                self.data_buffer[symbol] = []
            
            self.data_buffer[symbol].append(data)
            
            # Keep buffer size manageable
            if len(self.data_buffer[symbol]) > self.max_buffer_size:
                self.data_buffer[symbol] = self.data_buffer[symbol][-self.max_buffer_size:]
            
            # Periodic cleanup
            self._periodic_cleanup()
    
    def _periodic_cleanup(self):
        """Perform periodic cleanup of old data"""
        current_time = time.time()
        if current_time - self.last_cleanup > self.buffer_cleanup_interval:
            self._cleanup_old_data()
            self.last_cleanup = current_time
    
    def _cleanup_old_data(self):
        """Clean up old data from buffers"""
        cutoff_time = datetime.now() - timedelta(hours=24)  # Keep last 24 hours
        
        with self.data_lock:
            for symbol in list(self.data_buffer.keys()):
                if symbol in self.data_buffer:
                    # Filter out old data
                    self.data_buffer[symbol] = [
                        dp for dp in self.data_buffer[symbol]
                        if dp.get('received_at', datetime.now()) > cutoff_time
                    ]
                    
                    # Remove empty buffers
                    if not self.data_buffer[symbol]:
                        del self.data_buffer[symbol]
        
        logger.debug("Cleaned up old data from buffers")
    
    def clear_buffer(self, symbol: str = None):
        """
        Clear data buffer for symbol(s)
        
        Args:
            symbol: Symbol to clear (if None, clears all)
        """
        with self.data_lock:
            if symbol:
                if symbol in self.data_buffer:
                    self.data_buffer[symbol].clear()
                    logger.info(f"Cleared data buffer for {symbol}")
            else:
                self.data_buffer.clear()
                logger.info("Cleared all data buffers")
    
    def get_statistics(self) -> Dict[str, Any]:
        """
        Get data manager statistics
        
        Returns:
            Dictionary with statistics
        """
        with self.data_lock:
            total_data_points = sum(len(buffer) for buffer in self.data_buffer.values())
            
            return {
                'subscribed_symbols': len(self.subscribers),
                'total_data_points': total_data_points,
                'buffer_memory_usage_mb': total_data_points * 0.001,  # Rough estimate
                'symbols': list(self.subscribers.keys()),
                'broker_connected': self.broker.is_connected if self.broker else False,
                'last_cleanup': self.last_cleanup
            } 