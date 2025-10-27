import time

class ProgressTracker:
    """
    A reusable progress tracker that logs crawling progress periodically.
    
    Usage:
        tracker = ProgressTracker(logger, log_interval=60)
        tracker.set_total(100)
        
        # After each item is processed:
        tracker.increment()
        
        # At the end:
        tracker.log_final()
    """
    
    def __init__(self, logger, log_interval=60):
        """
        Initialize progress tracker.
        
        Args:
            logger: Logger instance to use for logging
            log_interval: Time in seconds between progress logs (default: 60)
        """
        self.logger = logger
        self.log_interval = log_interval
        self.total = 0
        self.completed = 0
        self.last_log_time = time.time()
        
    def set_total(self, total):
        """Set the total number of items to process."""
        self.total = total
        self.logger.info(f'Starting progress tracking: {total} items total')
        
    def increment(self, count=1):
        """
        Increment the completed counter and log if interval has passed.
        
        Args:
            count: Number of items to increment by (default: 1)
        """
        self.completed += count
        self._log_if_needed()
        
    def _log_if_needed(self):
        """Log progress if enough time has passed since last log."""
        current_time = time.time()
        if current_time - self.last_log_time >= self.log_interval:
            self._log_progress()
            self.last_log_time = current_time
            
    def _log_progress(self):
        """Log current progress."""
        if self.total > 0:
            percentage = (self.completed / self.total) * 100
            remaining = self.total - self.completed
            self.logger.info(
                f'Progress: {self.completed}/{self.total} '
                f'({percentage:.2f}%) completed, {remaining} remaining'
            )
        else:
            self.logger.info(f'Progress: {self.completed} items completed')
            
    def log_final(self):
        """Force log the final progress."""
        self._log_progress()
        if self.completed >= self.total and self.total > 0:
            self.logger.info('✓ All items completed successfully')
        elif self.total > 0:
            self.logger.warning(
                f'⚠ Incomplete: {self.total - self.completed} items not processed'
            )
            
    def get_stats(self):
        """
        Get current statistics.
        
        Returns:
            dict: Dictionary with 'total', 'completed', 'remaining', and 'percentage'
        """
        remaining = self.total - self.completed if self.total > 0 else 0
        percentage = (self.completed / self.total * 100) if self.total > 0 else 0
        
        return {
            'total': self.total,
            'completed': self.completed,
            'remaining': remaining,
            'percentage': percentage
        }
