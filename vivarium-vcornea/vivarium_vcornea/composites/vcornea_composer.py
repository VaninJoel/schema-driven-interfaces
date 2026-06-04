# vcornea_composer.py

from vivarium.core.composer import Composer
from vivarium_vcornea.processes.vcornea_process import VCorneaProcess


class VCorneaComposer(Composer):
    """
    Standard composer for vCornea simulations.
    
    This provides the basic pattern for composing vCornea simulations.
    For more complex studies, users can extend this or create their own composers.
    
    Usage:
        config = create_vcornea_config(...)
        composer = VCorneaComposer({'vcornea': config})
        composite = composer.generate()
    """
    
    defaults = {}
    
    def generate_processes(self, config):
        """Generate the vCornea process."""
        return {
            'vcornea': VCorneaProcess(config['vcornea'])
        }
    
    def generate_topology(self, config):
        """Generate standard single-process topology."""
        return {
            'vcornea': {
                'inputs': ('inputs',),
                'outputs': ('outputs',),
            }
        }