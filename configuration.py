"""Contains transformer configuration information
"""
from agpypeline.configuration import Configuration


class ConfigurationRgbBase(Configuration):
    """Configuration for RGB Plot base transformer template"""
    # Silence this error until we have public methods
    # pylint: disable=too-few-public-methods
    # The version number of the transformer
    transformer_version = '1.0'

    # The transformer description
    transformer_description = 'Base for plot-level RGB-based algorithm transformers'

    # Short name of the transformer
    transformer_name = 'rgb-plot-level-base'

    # The sensor associated with the transformer
    transformer_sensor = 'stereoTop'

    # The transformer type (eg: 'rgbmask', 'plotclipper')
    transformer_type = 'rgb.algorithm.base'

    # The name of the author of the extractor
    author_name = 'Chris Schnaufer'

    # The email of the author of the extractor
    author_email = 'schnaufer@email.arizona.edu'

    # Contributors to this transformer
    contributors = []

    # Repository URI of where the source code lives
    repository = 'https://github.com/AgPipeline/plot-base-rgb'
