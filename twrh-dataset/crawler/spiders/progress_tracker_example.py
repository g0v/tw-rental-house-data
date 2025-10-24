"""
Example usage of ProgressTracker

This module demonstrates how to use the ProgressTracker class
for different crawling scenarios.
"""

from .progress_tracker import ProgressTracker
import logging

# Example 1: Basic usage with a simple loop
def example_basic_usage():
    logger = logging.getLogger(__name__)
    tracker = ProgressTracker(logger, log_interval=60)
    
    items = range(1000)
    tracker.set_total(len(items))
    
    for item in items:
        # Process item
        process_item(item)
        
        # Track progress
        tracker.increment()
    
    # Log final statistics
    tracker.log_final()


# Example 2: Custom log interval (every 30 seconds)
def example_custom_interval():
    logger = logging.getLogger(__name__)
    tracker = ProgressTracker(logger, log_interval=30)
    
    tracker.set_total(500)
    
    for i in range(500):
        # Do work
        tracker.increment()
    
    tracker.log_final()


# Example 3: Batch increment
def example_batch_increment():
    logger = logging.getLogger(__name__)
    tracker = ProgressTracker(logger, log_interval=60)
    
    batch_size = 10
    total_batches = 100
    tracker.set_total(total_batches * batch_size)
    
    for batch in range(total_batches):
        # Process batch of items
        process_batch(batch_size)
        
        # Increment by batch size
        tracker.increment(count=batch_size)
    
    tracker.log_final()


# Example 4: Get statistics programmatically
def example_get_stats():
    logger = logging.getLogger(__name__)
    tracker = ProgressTracker(logger, log_interval=60)
    
    tracker.set_total(100)
    tracker.increment(25)
    
    stats = tracker.get_stats()
    print(f"Total: {stats['total']}")
    print(f"Completed: {stats['completed']}")
    print(f"Remaining: {stats['remaining']}")
    print(f"Percentage: {stats['percentage']:.2f}%")
    
    tracker.log_final()


# Example 5: Integration with PersistQueue (see detail591_spider.py)
def example_persist_queue_integration():
    """
    In detail591_spider.py, the ProgressTracker is integrated with PersistQueue:
    
    1. PersistQueue initializes ProgressTracker in __init__:
       self.progress_tracker = ProgressTracker(logger, log_interval=60)
    
    2. Spider calls init_progress_tracking() before starting:
       self.persist_queue.init_progress_tracking()
    
    3. PersistQueue increments after each successful parse:
       self.progress_tracker.increment()  # in parser_wrapper
    
    4. Spider logs final progress:
       self.persist_queue.progress_tracker.log_final()
    """
    pass


# Dummy functions for examples
def process_item(item):
    pass

def process_batch(size):
    pass
