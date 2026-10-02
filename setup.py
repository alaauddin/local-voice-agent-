import os
from pathlib import Path

from Cython.Build import cythonize
from setuptools import setup


PACKAGE_ROOTS = (Path("kiosk_agent"), Path("wazen_local"))


def application_modules() -> list[str]:
    """Return every runtime module that can be represented as a C extension."""
    return [
        str(path)
        for root in PACKAGE_ROOTS
        for path in root.rglob("*.py")
        # Keep package markers as Python so standard package discovery remains
        # predictable for Django, Celery, and migration discovery.
        if path.name != "__init__.py"
        # Django migration names begin with digits, which are valid for its
        # dynamic importer but invalid as native extension module names.
        and "migrations" not in path.parts
        # Tests are development inputs, not production runtime code.
        and "tests" not in path.parts
    ]


setup(
    name="sunset-kiosk-native",
    version="1.0.0",
    ext_modules=cythonize(
        application_modules(),
        compiler_directives={
            "language_level": 3,
            # Django, DRF, and Celery inspect call signatures at runtime.
            "binding": True,
            "embedsignature": True,
            # Apply safe inference to local variables where Cython can prove a
            # native representation without changing Python semantics.
            "infer_types": True,
            # Django frequently passes str/int subclasses (for example
            # TextChoices). PEP-484 annotations must not become exact C types.
            "annotation_typing": False,
            "always_allow_keywords": True,
        },
        annotate=False,
        nthreads=os.cpu_count() or 1,
    ),
)
