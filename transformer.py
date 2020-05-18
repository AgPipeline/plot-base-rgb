"""Base of plot-level RGB transformer
"""
import argparse
import datetime
import logging
import math
import os
import random
import time
from typing import Optional
import osr
import numpy as np

import gdal
from osgeo import ogr

import transformer_class
import algorithm_rgb

# Number of tries to open a CSV file before we give up
MAX_CSV_FILE_OPEN_TRIES = 10

# Maximum number of seconds a single wait for file open can take
MAX_FILE_OPEN_SLEEP_SEC = 30

# Array of trait names that should have array values associated with them
TRAIT_NAME_ARRAY_VALUE = ['canopy_cover', 'site']

# Mapping of default trait names to fixed values
TRAIT_NAME_MAP = {
    'local_datetime': None,
    'access_level': '2',
    'species': 'Unknown',
    'site': '',
    'citation_author': '"Unknown"',
    'citation_year': '0000',
    'citation_title': 'Unknown',
    'method': 'Unknown'
}

# Trait names arrays
CSV_TRAIT_NAMES = ['germplasmName', 'site', 'timestamp', 'lat', 'lon', 'citation_author', 'citation_year', 'citation_title']
GEO_TRAIT_NAMES = ['site', 'trait', 'lat', 'lon', 'dp_time', 'source', 'value', 'timestamp']
BETYDB_TRAIT_NAMES = ['local_datetime', 'access_level', 'species', 'site', 'citation_author', 'citation_year', 'citation_title',
                      'method']

# Used to generate random numbers
RANDOM_GENERATOR = None

# The LAT-LON EPSG code to use
LAT_LON_EPSG_CODE = 4326

# Names of files generated
FILE_NAME_CSV = "rgb_plot.csv"
FILE_NAME_GEO_CSV = "rgb_plot_geo.csv"
FILE_NAME_BETYDB_CSV = "rgb_plot_betydb.csv"

class __internal__():
    """Class containing functions for this file only
    """
    # pylint: disable=too-many-public-methods
    def __init__(self):
        """Perform class level initialization
        """

    @staticmethod
    def get_algorithm_definition_bool(variable_name: str, default_value: bool = False) -> bool:
        """Returns the value of the algorithm definition as a boolean value
        Arguments:
            variable_name: the name of the variable to look up
            default_value: the default value to return if the variable is not defined or is None
        """
        value = False
        if hasattr(algorithm_rgb, variable_name):
            temp_name = getattr(algorithm_rgb, variable_name)
            if temp_name:
                value = True
            elif temp_name is not None:
                value = False

        return value if value else default_value

    @staticmethod
    def get_algorithm_definition_str(variable_name: str, default_value: str = '') -> str:
        """Returns the value of the string variable found in algorithm_rgb
        Arguments:
            variable_name: the name of the definition to find
            default_value: the default value to return if the variable isn't defined, is not a string, or has an empty value
        Notes:
            If the variable can't be determined, the default value is returned
        """
        value = None
        if hasattr(algorithm_rgb, variable_name):
            temp_name = getattr(algorithm_rgb, variable_name)
            if isinstance(temp_name, str):
                value = temp_name.strip()

        return value if value else default_value

    @staticmethod
    def get_algorithm_name() -> str:
        """Convenience function for returning the name of the algorithm
        """
        return __internal__.get_algorithm_definition_str('ALGORITHM_NAME', 'unknown algorithm')

    @staticmethod
    def get_algorithm_variable_list(definition_name: str) -> list:
        """Returns a list containing the variable information defined by the algorithm
        Arguments:
            definition_name: name of the variable definition to look up
        Return:
            A list of variable strings
        Note:
            Assumes that multiple variable-related strings are comma separated
        """
        if not hasattr(algorithm_rgb, definition_name):
            raise RuntimeError("Unable to find %s defined in algorithm_rgb code" % definition_name)

        names = getattr(algorithm_rgb, definition_name).strip()
        if not names:
            raise RuntimeError("Empty %s definition specified in algorithm_rgb code" % definition_name)

        return names.split(',')

    @staticmethod
    def get_algorithm_variable_labels() -> list:
        """Returns a list containing all the variable names defined by the algorithm
        Return:
            A list of variable names
        """
        return_labels = []
        if hasattr(algorithm_rgb, 'VARIABLE_LABELS'):
            labels = getattr(algorithm_rgb, 'VARIABLE_LABELS').strip()
            if labels:
                return_labels = labels.split(',')

        return return_labels

    @staticmethod
    def recursive_metadata_search(metadata_list: list, search_key: str, special_key: str = None) -> str:
        """Performs a depth-first search for the key in the metadata and returns the found value
        Arguments:
            metadata_list: the metadata in which to look
            search_key: the key to look for in the metadata
            special_key: optional special key to look up the key under. If specified and found, the found value takes precedence
        Return:
            Returns the found key value, or an empty string
        Notes:
            The metadata is searched recursively for the key. If a key is found under the special key, it will be
            returned regardless of whether there's a key found elsewhere in the metadata
        """
        top_found_name = ''
        return_found_name = None
        for metadata in metadata_list:
            for key in metadata:
                if key == search_key:
                    top_found_name = metadata[key]
                if special_key and key == special_key:
                    if isinstance(metadata[key], dict):
                        temp_found_name = __internal__.recursive_metadata_search([metadata[key]], search_key, special_key)
                        if temp_found_name:
                            return_found_name = str(temp_found_name)
                            break
                elif isinstance(metadata[key], dict):
                    temp_found_name = __internal__.recursive_metadata_search([metadata[key]], search_key, special_key)
                    if temp_found_name:
                        top_found_name = str(temp_found_name)

        return return_found_name if return_found_name is not None else top_found_name

    @staticmethod
    def find_metadata_value(metadata_list: list, key_terms: list) -> str:
        """Returns the first found value associated with a key
        Arguments:
            metadata_list: the metadata to search
            key_terms: the keys to look for
        Returns:
            Returns the found value or an empty string
        """
        for one_key in key_terms:
            value = __internal__.recursive_metadata_search(metadata_list, one_key)
            if value:
                return value

        return ''

    @staticmethod
    def prepare_algorithm_metadata() -> tuple:
        """Prepares metadata with algorithm information
        Return:
            Returns a tuple with the name of the algorithm and a dictionary with information on the algorithm
        """
        return (__internal__.get_algorithm_definition_str('ALGORITHM_NAME', 'unknown'),
                {
                    'version': __internal__.get_algorithm_definition_str('VERSION', 'x.y'),
                    'traits': __internal__.get_algorithm_definition_str('VARIABLE_NAMES', ''),
                    'units': __internal__.get_algorithm_definition_str('VARIABLE_UNITS', ''),
                    'labels': __internal__.get_algorithm_definition_str('VARIABLE_LABELS', '')
                })

    @staticmethod
    def image_get_geobounds(filename: str) -> list:
        """Uses gdal functionality to retrieve rectilinear boundaries from the file

        Args:
            filename: path of the file to get the boundaries from

        Returns:
            The upper-left and calculated lower-right boundaries of the image in a list upon success.
            The values are returned in following order: min_y, max_y, min_x, max_x. A list of numpy.nan
            is returned if the boundaries can't be determined
        """
        try:
            src = gdal.Open(filename)
            ulx, xres, _, uly, _, yres = src.GetGeoTransform()
            lrx = ulx + (src.RasterXSize * xres)
            lry = uly + (src.RasterYSize * yres)

            min_y = min(uly, lry)
            max_y = max(uly, lry)
            min_x = min(ulx, lrx)
            max_x = max(ulx, lrx)

            return [min_y, max_y, min_x, max_x]
        except Exception as ex:
            logging.warning("[image_get_geobounds] Exception caught processing file: %s", filename)
            logging.warning("[image_get_geobounds] Exception: %s", str(ex))

        return [np.nan, np.nan, np.nan, np.nan]

    @staticmethod
    def get_epsg(filename):
        """Returns the EPSG of the geo-referenced image file
        Args:
            filename(str): path of the file to retrieve the EPSG code from
        Return:
            Returns the found EPSG code, or None if it's not found or an error ocurred
        """
        try:
            src = gdal.Open(filename)

            proj = osr.SpatialReference(wkt=src.GetProjection())

            return proj.GetAttrValue('AUTHORITY', 1)
        except Exception as ex:
            logging.warning("[get_epsg] Exception caught processing file: %s", filename)
            logging.warning("[get_epsg] Exception: %s", str(ex))

        return None

    @staticmethod
    def get_centroid_latlon(filename: str):
        """Returns the centroid of the geo-referenced image file as an OGR point
        Arguments:
            filename: the path to the file to get the centroid from
        Returns:
            Returns the centroid of the geometry loaded from the file in lat-lon coordinates
        Exceptions:
            RuntimeError is raised if the image is not a geo referenced image with an EPSG code,
            the EPSG code is not supported, or another problems occurs
        """
        bounds = __internal__.image_get_geobounds(filename)
        if bounds[0] == np.nan:
            msg = "File is not a geo-referenced image file: %s" % filename
            logging.error(msg)
            raise RuntimeError(msg)

        epsg = __internal__.get_epsg(filename)
        if epsg is None:
            msg = "EPSG is not found in image file: '%s'" % filename
            logging.error(msg)
            raise RuntimeError(msg)

        ring = ogr.Geometry(ogr.wkbLinearRing)
        ring.AddPoint(bounds[2], bounds[1])  # Upper left
        ring.AddPoint(bounds[3], bounds[1])  # Upper right
        ring.AddPoint(bounds[3], bounds[0])  # lower right
        ring.AddPoint(bounds[2], bounds[0])  # lower left
        ring.AddPoint(bounds[2], bounds[1])  # Closing the polygon

        poly = ogr.Geometry(ogr.wkbPolygon)
        poly.AddGeometry(ring)

        ref_sys = osr.SpatialReference()
        if ref_sys.ImportFromEPSG(int(epsg)) == ogr.OGRERR_NONE:
            poly.AssignSpatialReference(ref_sys)
        else:
            msg = "Failed to import EPSG %s for image file %s" % (str(epsg), filename)
            logging.error(msg)
            raise RuntimeError(msg)

        # Convert the polygon to lat-lon
        dest_spatial = osr.SpatialReference()
        if dest_spatial.ImportFromEPSG(int(LAT_LON_EPSG_CODE)) != ogr.OGRERR_NONE:
            msg = "Failed to import EPSG %s for conversion to lat-lon" % str(LAT_LON_EPSG_CODE)
            logging.error(msg)
            raise RuntimeError(msg)

        transform = osr.CoordinateTransformation(ref_sys, dest_spatial)
        new_src = poly.Clone()
        if new_src:
            new_src.Transform(transform)
        else:
            msg = "Failed to transform file polygon to lat-lon" % filename
            logging.error(msg)
            raise RuntimeError(msg)

        return new_src.Centroid()

    @staticmethod
    def get_time_stamps(iso_timestamp: str) -> list:
        """Returns the date and the local time (offset is stripped) derived from the passed in timestamp
        Return:
            A list consisting of the date (YYYY-MM-DD) and a local timestamp (YYYY-MM-DDTHH:MM:SS)
        """
        timestamp = datetime.datetime.fromisoformat(iso_timestamp)

        return [timestamp.strftime('%Y-%m-%d'), timestamp.strftime('%Y-%m-%dT%H:%M:%S')]

    @staticmethod
    def get_open_backoff(prev: float = None) -> float:
        """Returns the number of seconds to back off from opening a file
        Args:
            prev(int or float): the previous return value from this function
        Return:
            Returns the number of seconds (including fractional seconds) to wait
        Note that the return value is deterministic, and always the same, when None is
        passed in
        """
        # pylint: disable=global-statement
        global RANDOM_GENERATOR
        global MAX_FILE_OPEN_SLEEP_SEC

        # Simple case
        if prev is None:
            return 1

        # Get a random number generator
        if RANDOM_GENERATOR is None:
            try:
                RANDOM_GENERATOR = random.SystemRandom()
            finally:
                # Set this so we don't try again
                RANDOM_GENERATOR = 0

        # Get a random number
        if RANDOM_GENERATOR:
            multiplier = RANDOM_GENERATOR.random()  # pylint: disable=no-member
        else:
            multiplier = random.random()

        # Calculate how long to sleep
        sleep = math.trunc(float(prev) * multiplier * 100) / 10.0
        if sleep > MAX_FILE_OPEN_SLEEP_SEC:
            sleep = max(0.1, math.trunc(multiplier * 100) / 10)

        return sleep

    @staticmethod
    def write_csv_file(filename, header, data):
        """Attempts to write out the data to the specified file. Will write the
           header information if it's the first call to write to the file.
           If the file is not available, it waits as configured until it becomes
           available, or returns an error.
           Args:
                filename(str): path to the file to write to
                header(str): Optional CSV formatted header to write to the file; can be set to None
                data(str): CSV formatted data to write to the file
            Return:
                Returns True if the file was written to and False otherwise
        """
        # pylint: disable=global-statement
        global MAX_CSV_FILE_OPEN_TRIES

        if not filename or not data:
            logging.error("Empty parameter passed to write_geo_csv")
            return False

        csv_file = None
        backoff_secs = None
        for tries in range(0, MAX_CSV_FILE_OPEN_TRIES):
            try:
                csv_file = open(filename, 'a+')
            except Exception as ex:
                # Ignore an exception here since we handle it below
                logging.debug("Exception caught while trying to open CSV file: %s", filename)
                logging.debug("Exception: %s", str(ex))

            if csv_file:
                break

            # If we can't open the file, back off and try again (unless it's our last try)
            if tries < MAX_CSV_FILE_OPEN_TRIES - 1:
                backoff_secs = __internal__.get_open_backoff(backoff_secs)
                logging.info("Sleeping for %s seconds before trying to open CSV file again", str(backoff_secs))
                time.sleep(backoff_secs)

        if not csv_file:
            logging.error("Unable to open CSV file for writing: '%s'", filename)
            return False

        wrote_file = False
        try:
            # Check if we need to write a header
            if os.fstat(csv_file.fileno()).st_size <= 0:
                csv_file.write(header + "\n")

            # Write out data
            csv_file.write(data + "\n")

            wrote_file = True
        except Exception as ex:
            logging.error("Exception while writing CSV file: '%s'", filename)
            logging.error("Exception: %s", str(ex))
            # Re-raise the exception
            raise ex from None
        finally:
            csv_file.close()

        # Return whether or not we wrote to the file
        return wrote_file

    @staticmethod
    def get_csv_fields(variable_names: list) -> list:
        """Returns the list of CSV field names as a list
        Arguments:
            variable_names: a list of trait variable names to add to the returned list
        """
        return CSV_TRAIT_NAMES + list(variable_names)

    @staticmethod
    def get_geo_fields() -> list:
        """Returns the supported field names as a list
        """
        return GEO_TRAIT_NAMES

    @staticmethod
    def get_bety_fields(variable_names: list) -> list:
        """Returns the supported field names as a list
        Arguments:
            variable_names: a list of trait variable names to add to the returned list
        """
        return BETYDB_TRAIT_NAMES + list(variable_names)

    @staticmethod
    def get_default_trait(trait_name):
        """Returns the default value for the trait name
        Args:
           trait_name(str): the name of the trait to return the default value for
        Return:
            If the default value for a trait is configured, that value is returned. Otherwise
            an empty string is returned.
        """
        # pylint: disable=global-statement
        global TRAIT_NAME_ARRAY_VALUE
        global TRAIT_NAME_MAP

        if trait_name in TRAIT_NAME_ARRAY_VALUE:
            return []  # Return an empty list when the name matches
        if trait_name in TRAIT_NAME_MAP:
            return TRAIT_NAME_MAP[trait_name]
        return ""

    @staticmethod
    def get_csv_header_fields() -> list:
        """Returns the list of header fields incorporating variable names, units, and labels
        Return:
             A list of strings that can be used as the header to a CSV file
        """
        header_fields = []
        variable_names = __internal__.get_algorithm_variable_list('VARIABLE_NAMES')
        variable_units = __internal__.get_algorithm_variable_list('VARIABLE_UNITS')
        variable_units_len = len(variable_units)
        variable_labels = __internal__.get_algorithm_variable_labels()
        variable_labels_len = len(variable_labels)

        if variable_units_len != len(variable_names):
            logging.warning("The number of variable units doesn't match the number of variable names")
            logging.warning("Continuing with defined variable units")
        if variable_labels_len and variable_labels_len != len(variable_names):
            logging.warning("The number of variable labels doesn't match the number of variable names")
            logging.warning("Continuing with defined variable labels")

        logging.debug("Variable names: %s", str(variable_names))
        logging.debug("Variable labels: %s", str(variable_labels))
        logging.debug("Variable units: %s", str(variable_units))

        for idx, field_name in enumerate(variable_names):
            field_header = field_name
            if idx < variable_labels_len:
                field_header += ' %s' % variable_labels[idx]
            if idx < variable_units_len:
                field_header += ' (%s)' % variable_units[idx]
            header_fields.append(field_header)

        logging.debug("Header fields: %s", str(CSV_TRAIT_NAMES + header_fields))
        return CSV_TRAIT_NAMES + header_fields

    @staticmethod
    def get_csv_traits_table(variable_names: list) -> tuple:
        """Returns the field names and default trait values
        Arguments:
            variable_names: a list of additional trait variable names
        Returns:
            A tuple containing the list of field names and a dictionary of default field values
        """
        # Compiled traits table
        fields = __internal__.get_csv_fields(variable_names)
        traits = {}
        for field_name in fields:
            traits[field_name] = __internal__.get_default_trait(field_name)

        if hasattr(algorithm_rgb, 'CITATION_AUTHOR') and getattr(algorithm_rgb, 'CITATION_AUTHOR'):
            traits['citation_author'] = getattr(algorithm_rgb, 'CITATION_AUTHOR')
        if hasattr(algorithm_rgb, 'CITATION_TITLE') and getattr(algorithm_rgb, 'CITATION_TITLE'):
            traits['citation_title'] = getattr(algorithm_rgb, 'CITATION_TITLE')
        if hasattr(algorithm_rgb, 'CITATION_YEAR') and getattr(algorithm_rgb, 'CITATION_YEAR'):
            traits['citation_year'] = getattr(algorithm_rgb, 'CITATION_YEAR')

        return (fields, traits)

    @staticmethod
    def get_geo_traits_table():
        """Returns the field names and default trait values
        Returns:
            A tuple containing the list of field names and a dictionary of default field values
        """
        fields = __internal__.get_geo_fields()
        traits = {}
        for field_name in fields:
            traits[field_name] = ""

        return (fields, traits)

    @staticmethod
    def get_bety_traits_table(variable_names: list) -> tuple:
        """Returns the field names and default trait values
        Arguments:
            variable_names: a list of additional trait variable names
        Returns:
            A tuple containing the list of field names and a dictionary of default field values
        """
        # Compiled traits table
        fields = __internal__.get_bety_fields(variable_names)
        traits = {}
        for field_name in fields:
            traits[field_name] = __internal__.get_default_trait(field_name)

        if hasattr(algorithm_rgb, 'CITATION_AUTHOR') and getattr(algorithm_rgb, 'CITATION_AUTHOR'):
            traits['citation_author'] = getattr(algorithm_rgb, 'CITATION_AUTHOR')
        if hasattr(algorithm_rgb, 'CITATION_TITLE') and getattr(algorithm_rgb, 'CITATION_TITLE'):
            traits['citation_title'] = getattr(algorithm_rgb, 'CITATION_TITLE')
        if hasattr(algorithm_rgb, 'CITATION_YEAR') and getattr(algorithm_rgb, 'CITATION_YEAR'):
            traits['citation_year'] = getattr(algorithm_rgb, 'CITATION_YEAR')
        if hasattr(algorithm_rgb, 'ALGORITHM_METHOD') and getattr(algorithm_rgb, 'ALGORITHM_METHOD'):
            traits['method'] = getattr(algorithm_rgb, 'ALGORITHM_METHOD')

        return (fields, traits)

    @staticmethod
    def generate_traits_list(fields, traits):
        """Returns an array of trait values
        Args:
            fields(list): the list of fields to look up and return
            traits(dict): contains the set of trait values to return
        Return:
            Returns an array of trait values taken from the traits parameter
        Notes:
            If a trait isn't found, it's assigned an empty string
        """
        # compose the summary traits
        trait_list = []
        for field_name in fields:
            if field_name in traits:
                trait_list.append(traits[field_name])
            else:
                trait_list.append(__internal__.get_default_trait(field_name))

        return trait_list

    @staticmethod
    def filter_file_list_by_ext(source_files: list, known_exts: list) -> list:
        """Returns the list of known files by extension
        Arguments:
            source_files: the list of source files to look through
            known_exts: the list of known extensions
        Return:
            Returns the list of files identified as image files
        """
        return_list = []

        # Skip files we don't know about
        for one_file in source_files:
            ext = os.path.splitext(one_file)[1].strip('.')
            if ext in known_exts:
                return_list.append(one_file)

        return return_list

    @staticmethod
    def determine_csv_path(path_list: list) -> Optional[str]:
        """Iterates over the list of paths and returns the first valid one
        Arguments:
            path_list: the list of paths to iterate over
        Return:
            The first found path that exists, or None if no paths are found
        """
        if not path_list:
            return None

        for one_path in path_list:
            logging.debug("Checking csv path: %s", str(one_path))
            if not one_path:
                continue
            logging.debug("Checking csv path exists: %s", str(one_path))
            if os.path.exists(one_path) and os.path.isdir(one_path):
                logging.debug("Returning CSV path: %s", str(one_path))
                return one_path

        logging.debug("Unable to find a CSV path")
        return None

    @staticmethod
    def get_csv_file_names(csv_path: str) -> list:
        """Returns the list of csv file paths
        Arguments:
            csv_path: the base path for the csv files
        Return:
            Returns the list of file paths: default CSV file, Geostreams CSV file, BETYdb CSV file
        """
        return [os.path.join(csv_path, FILE_NAME_CSV),
                os.path.join(csv_path, FILE_NAME_GEO_CSV),
                os.path.join(csv_path, FILE_NAME_BETYDB_CSV)]


    @staticmethod
    def validate_calc_value(calc_value, variable_names: list) -> list:
        """Returns a list of the validated value(s) as compared against type and length of variable names
        Arguments:
            calc_value: the calculated value(s) to validate (int, float, str, dict, list, etc.)
            variable_names: the list of the names of expected variables
        Return:
            Returns the validated values as a list
        Exceptions:
            RuntimeError is raised if the calc_value is not a supported type or the number of values doesn't match
            the expected number (as determined by variable_names)
        """
        if isinstance(calc_value, set):
            raise RuntimeError("A 'set' type of data was returned and isn't supported. Please use a list or a tuple instead")

        # Special case handling for special return dict (values and other stuff)
        if isinstance(calc_value, dict) and 'values' in calc_value:
            values_result = calc_value['values']
        else:
            values_result = calc_value

        # Get the values into list form
        values = []
        len_variable_names = len(variable_names)
        if isinstance(values_result, dict):
            # Assume the dictionary is going to have field names with their values
            # We check whether we have the correct number of fields later. This also
            # filters out extra fields
            values = []
            for key in variable_names:
                if key in values_result:
                    values.append(values_result[key])
        elif not isinstance(values_result, (list, tuple)):
            values = [values_result]

        # Sanity check our values
        len_calc_value = len(values)
        if not len_calc_value == len_variable_names:
            raise RuntimeError("Incorrect number of values returned. Expected " + str(len_variable_names) +
                               " and received " + str(len_calc_value))

        return values

    @staticmethod
    def write_trait_csv(filename: str, header: str, fields: list, traits: dict) -> None:
        """Writes the trait data to the specified CSV file
        Arguments:
            filename: the name of the file to write to
            header: the file header to be written as needed
            fields: the list of field names to save to the file
            traits: the trait values to write
        """
        trait_list = __internal__.generate_traits_list(fields, traits)
        csv_data = ','.join(map(str, trait_list))
        __internal__.write_csv_file(filename, header, csv_data)


def add_parameters(parser: argparse.ArgumentParser) -> None:
    """Adds parameters
    Arguments:
        parser: instance of argparse
    """
    supported_files = [FILE_NAME_CSV + ': basic CSV file with calculated values']
    if __internal__.get_algorithm_definition_bool('WRITE_GEOSTREAMS_CSV', True):
        supported_files.append(FILE_NAME_BETYDB_CSV + ': TERRA REF Geostreams compatible CSV file')
    if __internal__.get_algorithm_definition_bool('WRITE_BETYDB_CSV', True):
        supported_files.append(FILE_NAME_BETYDB_CSV + ': BETYdb compatible CSV file')

    parser.description = 'Plot level RGB algorithm: ' + __internal__.get_algorithm_name() + \
                         ' version ' + __internal__.get_algorithm_definition_str('VERSION', 'x.y')

    parser.add_argument('--csv_path', help='the path to use when generating the CSV files')
    parser.add_argument('--geostreams_csv', action='store_true',
                        help='override to always create the TERRA REF Geostreams-compatible CSV file')
    parser.add_argument('--betydb_csv', action='store_true', help='override to always create the BETYdb-compatible CSV file')

    parser.epilog = 'The following files are created in the specified csv path by default: ' + \
                    '\n  ' + '\n  '.join(supported_files) + '\n' + \
                    ' author ' + __internal__.get_algorithm_definition_str('ALGORITHM_AUTHOR', 'mystery author') + \
                    ' ' + __internal__.get_algorithm_definition_str('ALGORITHM_AUTHOR_EMAIL', '(no email)')


def check_continue(transformer: transformer_class.Transformer, check_md: dict, transformer_md: list, full_md: list) -> tuple:
    """Checks if conditions are right for continuing processing
    Arguments:
        transformer: instance of transformer class
        check_md: request specific metadata
        transformer_md: metadata associated with previous runs of the transformer
        full_md: the full set of metadata available to the transformer
    Return:
        Returns a list containing the return code for continuing or not, and
        an error message if there's an error
    """
    # pylint: disable=unused-argument
    # Look for at least one image file in the list provided
    found_image = False
    for one_file in check_md['list_files']():
        ext = os.path.splitext(one_file)[1].strip('.')
        if ext in transformer.supported_image_file_exts:
            found_image = True
            break

    if not found_image:
        logging.debug("Image not found in list of files. Supported types are: %s", ", ".join(transformer.supported_image_file_exts))

    return (0) if found_image else (-1000, "Unable to find an image in the list of files")


def perform_process(transformer: transformer_class.Transformer, check_md: dict, transformer_md: list, full_md: list) -> dict:
    """Performs the processing of the data
    Arguments:
        transformer: instance of transformer class
        check_md: request specific metadata
        transformer_md: metadata associated with previous runs of the transformer
        full_md: the full set of metadata available to the transformer
    Return:
        Returns a dictionary with the results of processing
    """
    # pylint: disable=unused-argument
    # The following pylint disables are here because to satisfy them would make the code unreadable
    # pylint: disable=too-many-statements, too-many-locals, too-many-branches

    # Environment checking
    if not hasattr(algorithm_rgb, 'calculate'):
        msg = "The 'calculate()' function was not found in algorithm_rgb.py"
        logging.error(msg)
        return {'code': -1001, 'error': msg}

    logging.debug("Working with check_md: %s", str(check_md))

    # Setup local variables
    variable_names = __internal__.get_algorithm_variable_list('VARIABLE_NAMES')

    csv_file, geostreams_csv_file, betydb_csv_file = __internal__.get_csv_file_names(
        __internal__.determine_csv_path([transformer.args.csv_path, check_md['working_folder']]))
    logging.debug("Calculated default CSV path: %s", csv_file)
    logging.debug("Calculated geostreams CSV path: %s", geostreams_csv_file)
    logging.debug("Calculated BETYdb CSV path: %s", betydb_csv_file)
    datestamp, localtime = __internal__.get_time_stamps(check_md['timestamp'])
    cultivar = __internal__.find_metadata_value(full_md, ['germplasmName', 'cultivar'])

    write_geostreams_csv = transformer.args.geostreams_csv or __internal__.get_algorithm_definition_bool('WRITE_GEOSTREAMS_CSV', True)
    write_betydb_csv = transformer.args.betydb_csv or __internal__.get_algorithm_definition_bool('WRITE_BETYDB_CSV', True)
    logging.info("Writing geostreams csv file: %s", "True" if write_geostreams_csv else "False")
    logging.info("Writing BETYdb csv file: %s", "True" if write_betydb_csv else "False")

    # Get default values and adjust as needed
    (csv_fields, csv_traits) = __internal__.get_csv_traits_table(variable_names)
    csv_traits['germplasmName'] = cultivar
    (geo_fields, geo_traits) = __internal__.get_geo_traits_table()
    (bety_fields, bety_traits) = __internal__.get_bety_traits_table(variable_names)
    bety_traits['species'] = cultivar

    csv_header = ','.join(map(str, __internal__.get_csv_header_fields()))
    geo_csv_header = ','.join(map(str, geo_fields))
    bety_csv_header = ','.join(map(str, bety_fields))

    # Process the image files
    num_image_files = 0
    entries_written = 0
    additional_files_list = []
    for one_file in __internal__.filter_file_list_by_ext(check_md['list_files'](), transformer.supported_image_file_exts):

        plot_name = None
        try:
            num_image_files += 1

            # Setup
            plot_name = __internal__.recursive_metadata_search(full_md, 'plot_name', one_file)
            centroid = __internal__.get_centroid_latlon(one_file)
            image_pix = np.array(gdal.Open(one_file).ReadAsArray())

            # Make the call and check the results
            calc_value = algorithm_rgb.calculate(image_pix)
            logging.debug("Calculated value is %s for file: %s", str(calc_value), one_file)
            if calc_value is None:
                continue

            if isinstance(calc_value, dict) and 'file' in calc_value and calc_value['file']:
                additional_files_list.extend(calc_value['file'])

            values = __internal__.validate_calc_value(calc_value, variable_names)
            logging.debug("Verified values are %s", str(values))

            geo_traits['site'] = plot_name
            geo_traits['lat'] = str(centroid.GetY())
            geo_traits['lon'] = str(centroid.GetX())
            geo_traits['dp_time'] = localtime
            geo_traits['source'] = one_file
            geo_traits['timestamp'] = datestamp

            # Write the data points geographically and otherwise
            for idx, trait_name in enumerate(variable_names):
                # Geostreams can only handle one field at a time so we write out one row per field/value pair
                geo_traits['trait'] = trait_name
                geo_traits['value'] = str(values[idx])
                if write_geostreams_csv:
                    __internal__.write_trait_csv(geostreams_csv_file, geo_csv_header, geo_fields, geo_traits)

                # csv and BETYdb can handle wide rows with multiple values so we just set the field
                # values here and write the single row after the loop
                csv_traits[variable_names[idx]] = str(values[idx])
                bety_traits[variable_names[idx]] = str(values[idx])

            csv_traits['site'] = plot_name
            csv_traits['timestamp'] = datestamp
            csv_traits['lat'] = str(centroid.GetY())
            csv_traits['lon'] = str(centroid.GetX())
            __internal__.write_trait_csv(csv_file, csv_header, csv_fields, csv_traits)

            bety_traits['site'] = plot_name
            bety_traits['local_datetime'] = localtime
            if write_betydb_csv:
                __internal__.write_trait_csv(betydb_csv_file, bety_csv_header, bety_fields, bety_traits)

            entries_written += 1

        except Exception as ex:
            logging.error("Error generating %s for %s", __internal__.get_algorithm_name(), str(plot_name))
            logging.error("Exception: %s", str(ex))
            continue

    if num_image_files == 0:
        logging.warning("No images were detected for processing")
    if entries_written == 0:
        logging.warning("No entries were written to CSV files")

    # Prepare the return information
    algorithm_name, algorithm_md = __internal__.prepare_algorithm_metadata()
    algorithm_md['files_processed'] = str(num_image_files)
    algorithm_md['lines_written'] = str(entries_written)
    if write_geostreams_csv:
        algorithm_md['wrote_geostreams'] = "Yes"
    if write_betydb_csv:
        algorithm_md['wrote_betydb'] = "Yes"

    file_md = []
    if entries_written:
        file_md.append({
            'path': csv_file,
            'key': 'csv'
        })
        if write_geostreams_csv:
            file_md.append({
                'path': geostreams_csv_file,
                'key': 'csv'
            })
        if write_betydb_csv:
            file_md.append({
                'path': betydb_csv_file,
                'key': 'csv'
            })

    for one_file in additional_files_list:
        file_path = str(one_file)
        if not os.path.exists(file_path):
            logging.warning("Additional return file not found to return: '%s'", file_path)
            continue
        logging.info("Adding additional file to results: '%s'", file_path)
        file_md.append({
            'path': file_path,
            'key': os.path.splitext(file_path)[1].lstrip('.')
        })

    return {'code': 0,
            'file': file_md,
            algorithm_name: algorithm_md
            }
