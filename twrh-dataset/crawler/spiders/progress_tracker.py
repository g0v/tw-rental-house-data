import json
import os
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
        # Overall tracking (persisted across batches)
        self.overall_total = 0
        self.overall_completed = 0
        self.progress_file = None
        
    def set_total(self, total):
        """Set the total number of items to process."""
        self.total = total
        self.logger.info(f'Starting progress tracking: {total} items total')

    def init_overall(self, progress_file, batch_total):
        """
        Initialize overall progress tracking with file persistence.

        On first batch: creates file with total=batch_total, completed=0.
        On subsequent batches: reads existing file to restore overall state.
        """
        self.progress_file = progress_file
        self.total = batch_total

        if os.path.exists(progress_file):
            with open(progress_file, 'r') as f:
                data = json.load(f)
            self.overall_total = data['total']
            self.overall_completed = data['completed']
            self.logger.info(
                f'Restored overall progress: {self.overall_completed}/{self.overall_total} '
                f'| Batch: {batch_total} items'
            )
        else:
            self.overall_total = batch_total
            self.overall_completed = 0
            self._write_progress_file()
            self.logger.info(
                f'Starting overall progress tracking: {batch_total} items total'
            )
    
    def increment_total(self, count=1):
        """
        Increment the total counter when new items are dynamically added.
        
        Args:
            count: Number of items to add to total (default: 1)
        """
        self.total += count
        
    def increment(self, count=1):
        """
        Increment the completed counter and log if interval has passed.
        
        Args:
            count: Number of items to increment by (default: 1)
        """
        self.completed += count
        if self.progress_file:
            self.overall_completed += count
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
            batch_msg = (
                f'Batch: {self.completed}/{self.total} '
                f'({percentage:.1f}%) completed, {remaining} remaining'
            )
            if self.progress_file and self.overall_total > 0:
                overall_pct = (self.overall_completed / self.overall_total) * 100
                self.logger.info(
                    f'{batch_msg} | Overall: {self.overall_completed}/{self.overall_total} ({overall_pct:.1f}%)'
                )
            else:
                self.logger.info(batch_msg)
        else:
            self.logger.info(f'Progress: {self.completed} items completed')
            
    def log_final(self):
        """Force log the final progress and persist overall state to file."""
        self._log_progress()
        if self.progress_file:
            self._write_progress_file()
            if self.overall_completed >= self.overall_total:
                self.logger.info('✓ All items completed successfully (overall)')
        elif self.completed >= self.total and self.total > 0:
            self.logger.info('✓ All items completed successfully')
        elif self.total > 0:
            self.logger.warning(
                f'⚠ Incomplete: {self.total - self.completed} items not processed'
            )
            
    def _write_progress_file(self):
        """Write current overall progress to file."""
        data = {'total': self.overall_total, 'completed': self.overall_completed}
        with open(self.progress_file, 'w') as f:
            json.dump(data, f)

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
