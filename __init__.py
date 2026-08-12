if __package__:
    from .h3_performance_prep.node import H3PerformanceScenePrep
else:
    from h3_performance_prep.node import H3PerformanceScenePrep

NODE_CLASS_MAPPINGS = {"H3PerformanceScenePrep": H3PerformanceScenePrep}
NODE_DISPLAY_NAME_MAPPINGS = {"H3PerformanceScenePrep": "H3 Performance Scene Prep"}
