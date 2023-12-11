"""
The structure of folders/extensions in this project as follows:

extensions/
    ext_category_folder/
        _some_ext_utils_folder/
        _some_ext_utils_file.py 
        # ^ those must start with "_" in order not to be confused with one of below:
        package_folder_ext/
            **package structure like ext**
        one_file_ext.py
    
    __init__.py  # this file
    beta.py  # special beta test ext file.
    zeta.py  # clean state of^

This particular file aims to collect those files into Tuple of extensions so end result of 
`get_extensions(test)` should be something like
>>> get_extensions(False) 
>>> (
>>>    'jishaku',
>>>    'extensions.fpc_notifs.dota',
>>>    'extensions.fpc_notifs.lol',
>>>    'extensions.community.welcome',
>>>    ...
>>> )

where full name for usual extensions consists of the following parts `extensions.ext_category.cog_name`.
"""
from __future__ import annotations

import importlib
import os
from pkgutil import iter_modules
from typing import Tuple

from base import BASE_EXTENSIONS

try:
    import _test

    TEST_EXTENSIONS = _test.TEST_EXTENSIONS
    USE_ALL_EXTENSIONS = _test.USE_ALL_EXTENSIONS
except ModuleNotFoundError:
    _test = None
    TEST_EXTENSIONS = tuple()
    USE_ALL_EXTENSIONS = True

# EXTENSIONS

IGNORED_EXTENSIONS = "beta"  # these are ignored in main bot.

# Packages
MY_PACKAGES = tuple(module.name for module in iter_modules(path=__path__))  # , prefix=f'{__package__}.'


def get_extensions(test: bool, reload: bool = False) -> Tuple[str, ...]:
    """
    Get tuple of extensions for bot to load.

    Note that this function is a bit more robust than needed according to description above.
    This function can also catch package extensions in "extensions/" folder itself like `beta.py`
    or like we had cog "extensions.fun" be one folder cog for a very long time (now it is "extensions.fun.fun")

    Parameters
    ----------
    test: :class: `bool`
        Whenever AluBot is used or its testing version YenBot.
        Maybe this whole production/testing part can be done better.
        If reader knows better - please, teach me.
    reload: :class: `bool` = False
        If `_test` module with TEST_EXTENSIONS should be reloaded.
        Used to force reload in manual text commands like `$reload all`.
    Returns
    -------
    Tuple[str, ...]
        tuple of extensions for bot to load
    """

    # get only extensions for testing
    if test and _test:
        if reload:
            importlib.reload(_test)
            test_extensions, use_all_extensions = _test.TEST_EXTENSIONS, _test.USE_ALL_EXTENSIONS
        else:
            test_extensions, use_all_extensions = TEST_EXTENSIONS, USE_ALL_EXTENSIONS

        if not use_all_extensions:
            return BASE_EXTENSIONS + tuple(f"extensions.{x}" for x in test_extensions)

    # production giga-gathering option.
    all_folders = [f.name for f in os.scandir("extensions") if f.is_dir() if not f.name.startswith("_")]

    ext_category_folders = [x for x in all_folders if x not in MY_PACKAGES]
    uncategorised_extensions = tuple(f"extensions.{x}" for x in MY_PACKAGES if x not in IGNORED_EXTENSIONS)

    categorised_extensions = tuple(
        module.name
        for folder in ext_category_folders
        for module in iter_modules(path=[f"extensions/{folder}"], prefix=f"extensions.{folder}.")
        if not module.name.rsplit(".", 1)[-1].startswith("_")
    )

    extensions = BASE_EXTENSIONS + uncategorised_extensions + categorised_extensions
    return extensions
