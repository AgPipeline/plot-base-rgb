# Transformer: base RGB Plot-level
<img src="https://github.com/az-digitalag/Drone-Processing-Pipeline/raw/07b1edc34a1faea501c80f583beb07f9d6b290bb/resources/drone-pipeline.png" width="100" />

Provides the base image, or code, for plot-level RGB transformers for the [Drone Processing Pipeline](https://osf.io/xdkcy/wiki/home/).

The motivation behind this code is to significantly reduce the overhead in knowledge and work needed to add scientific algorithms to the pipeline.

##  What's provided
The transformer creates output CSV files in single process, or multi-process environments.
If the output CSV files don't exist, they are created and initialized (the CSV header is written identifying the fields).
If the output CSV files already exist, rows are appended to the files.
No checks are made to determine if a particular entry already exists in the CSV files, data is just appended.

By default a generic CSV file is produced, as well as CSV files compatible with [TERRA REF Geostreams](https://docs.terraref.org/user-manual/data-products/environmental-conditions) and with [BETYDB](https://www.betydb.org/).

### Changing default CSV behavior
Algorithm writers have the ability to override this default behavior with TERRA REF Geostreams and BETYdb through the definition of variables in their implementation file.
* WRITE_GEOSTREAMS_CSV - if defined at the global level and set to `False` will suppress writing TERRA REF Geostreams CSV data for an algorithm.
* WRITE_BETYDB_CSV - if defined at the global level and set to `False` will suppress writing BETYdb CSV data for an algorithm.

In case people executing an algorithm wish to generate BETYdb or TERRA REF Geostreams CSV files, there are command line arguments that override the just mentioned global variable values to force writing. 
Of course, these command line arguments are not necessary if the files are being written by default.

### Output path
The `--csv_path` parameter is key to getting multiple instances of RGB plot-level transformers writing to the same file.
For each instance of the same transformer that's run (either single- or multi-process), using the same path indicates that the produced data should be appended to the CSV files (dependent upon runtime environments).
Of course, if the file doesn't already exist it's first created and the CSV header written before data is written.

If writing all the data to the same file isn't possible, or not desirable, this parameter can be modified to allow each instance to write its own file (including the CSV header).

Note: if using Docker images this path is relative to the code running inside the container.

## Supported return values
There are two styles of return values from the algorithm that are supported.

The first are simple returns.
These are either a single value, an iterable of one or more return values, or a dictionary containing the value names and the value(s).
If using the dictionary approach, the variable names as defined by the algorithm writer are used as the lookup key to obtain the value.
For example:
```python
# Single value
33.00

# Iterable
[1, 2, 3]

# Dictionary: 'first' and 'second' would be the defined variable names
{'first': 1, 'second': 2}
``` 

The second style is a dictionary with a 'values' key with support for a 'file' key.
When using this style, the value associated with the 'values' key is the same as the simple return defined just above.
The 'file' key is assumed to contain a list of files that should be returned.
The files specified with the 'file' key are not copied so care should be taken by the algorithm writer to not overwrite files that are being returned.
The full path to each file should be specified.

```python
# Return value without files
{'values': 33.00}

# Return values and files
{'values': [1, 2, 3], 'files': ['/mnt/file1.tif', '/mnt/file2.tif']}
```