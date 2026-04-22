import threading
import time
import logging
from typing import Optional, Dict, Any
from enum import Enum

# Import your modules
import leds
import music
from arduino import send_command

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class CelebrationType(Enum):
    """Different types of celebrations for different achievements"""
    BASIC = "basic"
    VICTORY = "victory"
    MILESTONE = "milestone"
    BIRTHDAY = "birthday"
    CUSTOM = "custom"

class CelebrationManager:
    """
    Enhanced celebration system with multiple celebration types,
    thread safety, and graceful cleanup.
    """
    
    def __init__(self):
        self.celebration_active = False
        self.celebration_lock = threading.Lock()
        self.celebration_thread: Optional[threading.Thread] = None
        self.stop_event = threading.Event()
        
        # Celebration configurations
        self.celebration_configs = {
            CelebrationType.BASIC: {
                'duration': 10,
                'led_effect': 'chase',
                'music': True,
                'movement': 'HAPPY',
                'repeat_movement': False
            },
            CelebrationType.VICTORY: {
                'duration': 20,
                'led_effect': 'rainbow',
                'music': True,
                'movement': 'VICTORY_DANCE',
                'repeat_movement': True
            },
            CelebrationType.MILESTONE: {
                'duration': 15,
                'led_effect': 'pulse',
                'music': True,
                'movement': 'SPIN',
                'repeat_movement': False
            },
            CelebrationType.BIRTHDAY: {
                'duration': 30,
                'led_effect': 'party',
                'music': True,
                'movement': 'PARTY',
                'repeat_movement': True
            }
        }
    
    def start_celebration(self, celebration_type: CelebrationType = CelebrationType.BASIC, 
                         custom_config: Optional[Dict[str, Any]] = None) -> bool:
        """
        Start a celebration routine.
        
        Args:
            celebration_type: Type of celebration to perform
            custom_config: Custom configuration to override defaults
            
        Returns:
            True if celebration started successfully, False if already active
        """
        with self.celebration_lock:
            if self.celebration_active:
                logger.warning("Celebration already active, ignoring new request")
                return False
            
            self.celebration_active = True
            self.stop_event.clear()
        
        # Get configuration
        config = self.celebration_configs.get(celebration_type, 
                                            self.celebration_configs[CelebrationType.BASIC]).copy()
        
        # Override with custom config if provided
        if custom_config:
            config.update(custom_config)
        
        # Start celebration in separate thread
        self.celebration_thread = threading.Thread(
            target=self._celebration_routine,
            args=(celebration_type, config),
            daemon=True,
            name=f"Celebration-{celebration_type.value}"
        )
        self.celebration_thread.start()
        
        logger.info(f"🎉 {celebration_type.value.title()} celebration started!")
        return True
    
    def stop_celebration(self, wait_for_completion: bool = False):
        """
        Stop the current celebration.
        
        Args:
            wait_for_completion: If True, wait for celebration thread to complete
        """
        logger.info("Stopping celebration...")
        self.stop_event.set()
        
        if wait_for_completion and self.celebration_thread and self.celebration_thread.is_alive():
            self.celebration_thread.join(timeout=5.0)  # Wait up to 5 seconds
        
        with self.celebration_lock:
            self.celebration_active = False
        
        # Clean up
        self._cleanup_celebration()
        logger.info("✅ Celebration stopped")
    
    def _celebration_routine(self, celebration_type: CelebrationType, config: Dict[str, Any]):
        """
        Internal celebration routine that runs in a separate thread.
        """
        try:
            duration = config['duration']
            start_time = time.time()
            
            # Start LED effects
            led_thread = self._start_led_effects(config['led_effect'])
            
            # Start music if enabled
            if config.get('music', True):
                self._start_music()
            
            # Start movement routine
            movement_thread = self._start_movement_routine(config)
            
            # Run celebration for specified duration
            while (time.time() - start_time) < duration and not self.stop_event.is_set():
                time.sleep(0.1)  # Check stop event frequently
            
            # Clean up threads
            if led_thread and led_thread.is_alive():
                # Stop LED effects (assuming leds module has a stop function)
                try:
                    leds.stop_effects()
                except AttributeError:
                    pass  # leds module might not have stop function
            
            if movement_thread and movement_thread.is_alive():
                movement_thread.join(timeout=2.0)
            
        except Exception as e:
            logger.error(f"Error in celebration routine: {e}")
        finally:
            with self.celebration_lock:
                self.celebration_active = False
            self._cleanup_celebration()
            logger.info(f"✅ {celebration_type.value.title()} celebration completed")
    
    def _start_led_effects(self, led_effect: str) -> Optional[threading.Thread]:
        """Start LED effects based on the specified effect type."""
        try:
            led_thread = None
            if led_effect == 'chase':
                led_thread = threading.Thread(target=leds.run_chase_effect, daemon=True)
            elif led_effect == 'rainbow':
                led_thread = threading.Thread(target=getattr(leds, 'run_rainbow_effect', leds.run_chase_effect), daemon=True)
            elif led_effect == 'pulse':
                led_thread = threading.Thread(target=getattr(leds, 'run_pulse_effect', leds.run_chase_effect), daemon=True)
            elif led_effect == 'party':
                led_thread = threading.Thread(target=getattr(leds, 'run_party_effect', leds.run_chase_effect), daemon=True)
            
            if led_thread:
                led_thread.start()
                return led_thread
                
        except Exception as e:
            logger.error(f"Failed to start LED effects: {e}")
        
        return None
    
    def _start_music(self):
        """Start music for the celebration."""
        try:
            music.play_next_track()
        except Exception as e:
            logger.error(f"Failed to start music: {e}")
    
    def _start_movement_routine(self, config: Dict[str, Any]) -> Optional[threading.Thread]:
        """Start movement routine based on configuration."""
        movement = config.get('movement')
        repeat = config.get('repeat_movement', False)
        
        if not movement:
            return None
        
        def movement_routine():
            try:
                if repeat:
                    while not self.stop_event.is_set():
                        send_command("dev00", movement)
                        if self.stop_event.wait(2.0):
                            break
                else:
                    send_command("dev00", movement)
            except Exception as e:
                logger.error(f"Error in movement routine: {e}")
        
        movement_thread = threading.Thread(target=movement_routine, daemon=True)
        movement_thread.start()
        return movement_thread
    
    def _cleanup_celebration(self):
        """Clean up after celebration ends."""
        try:
            send_command("dev00", "STOP")
            music.stop_music()
            leds.stop_effects()
        except Exception as e:
            logger.error(f"Error during celebration cleanup: {e}")
    
    def is_celebrating(self) -> bool:
        """Check if a celebration is currently active."""
        with self.celebration_lock:
            return self.celebration_active
    
    def get_celebration_status(self) -> Dict[str, Any]:
        """Get current celebration status."""
        with self.celebration_lock:
            return {
                'active': self.celebration_active,
                'thread_alive': self.celebration_thread.is_alive() if self.celebration_thread else False
            }

# Create global celebration manager instance
celebration_manager = CelebrationManager()

# Convenience functions for backward compatibility
def start_celebration(celebration_type: CelebrationType = CelebrationType.BASIC) -> bool:
    """Start a celebration routine."""
    return celebration_manager.start_celebration(celebration_type)

def stop_celebration():
    """Stop the current celebration."""
    celebration_manager.stop_celebration()

def is_celebrating() -> bool:
    """Check if currently celebrating."""
    return celebration_manager.is_celebrating()

# Legacy function for backward compatibility
def celebration_routine():
    """Legacy celebration routine for backward compatibility."""
    return celebration_manager.start_celebration(CelebrationType.BASIC)

# Example usage functions
def celebrate_goal_reached():
    """Celebrate reaching a goal or milestone."""
    return celebration_manager.start_celebration(CelebrationType.MILESTONE)

def celebrate_victory():
    """Celebrate a major victory or achievement."""
    return celebration_manager.start_celebration(CelebrationType.VICTORY)

def celebrate_birthday():
    """Special birthday celebration."""
    return celebration_manager.start_celebration(CelebrationType.BIRTHDAY)

def custom_celebration(duration: int, led_effect: str, movement: str, repeat_movement: bool = False):
    """Create a custom celebration with specific parameters."""
    custom_config = {
        'duration': duration,
        'led_effect': led_effect,
        'movement': movement,
        'repeat_movement': repeat_movement
    }
    return celebration_manager.start_celebration(CelebrationType.CUSTOM, custom_config)

# Context manager for celebrations
class CelebrationContext:
    """Context manager for celebrations that ensures proper cleanup."""
    
    def __init__(self, celebration_type: CelebrationType = CelebrationType.BASIC):
        self.celebration_type = celebration_type
        self.started = False
    
    def __enter__(self):
        self.started = celebration_manager.start_celebration(self.celebration_type)
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.started:
            celebration_manager.stop_celebration(wait_for_completion=True)

# Example usage:
if __name__ == "__main__":
    # Test different celebration types
    print("Testing celebration system...")
    
    # Basic celebration
    start_celebration(CelebrationType.BASIC)
    time.sleep(3)
    stop_celebration()
    
    time.sleep(1)
    
    # Custom celebration
    custom_celebration(duration=5, led_effect='chase', movement='SPIN', repeat_movement=True)
    time.sleep(6)
    
    # Using context manager
    print("Testing context manager...")
    with CelebrationContext(CelebrationType.VICTORY) as celebration:
        time.sleep(3)
        print("Celebration will auto-stop when exiting context")
    
    print("All tests completed!")