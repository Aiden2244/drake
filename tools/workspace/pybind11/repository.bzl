load("//tools/workspace:generate_file.bzl", "generate_file")
load("//tools/workspace:github.bzl", "github_archive")

# Using the `drake` branch of this repository.
_REPOSITORY = "RobotLocomotion/pybind11"

# When upgrading this commit, check the version header within
#  https://github.com/RobotLocomotion/pybind11/blob/drake/include/pybind11/detail/common.h
# and if it has changed, then update the version number in the two
# pybind11-*.cmake files in the current directory to match.
#
# DO NOT MERGE: Currently on a personal branch:
# https://github.com/rpoyner-tri/pybind11/releases/tag/pybind11-with-minimal-patches-tests-pass
_COMMIT = "f63a772515fbf4f7cdf7488dadfcfccb330ff28c"

_SHA256 = "898cd8cfd609776dfd155b0324b47ae13fb882b336c04289aac1000c8061a87e"

def pybind11_repository(
        name,
        mirrors = None):
    github_archive(
        name = name,
        repository = _REPOSITORY,
        commit = _COMMIT,
        sha256 = _SHA256,
        build_file = ":package.BUILD.bazel",
        patches = [
            # DO NOT MERGE: already picked into the _COMMIT above.
            # ":patches/check_signature_infection.patch",
        ],
        mirrors = mirrors,
    )

def generate_pybind11_version_py_file(name):
    vars = dict(
        repository = repr(_REPOSITORY),
        commit = repr(_COMMIT),
        sha256 = repr(_SHA256),
    )
    generate_file(
        name = name,
        content = '''# noqa: shebang
"""
Provides information on the external fork of `pybind11` used by `pydrake`.
"""

repository = {repository}
commit = {commit}
sha256 = {sha256}
'''.format(**vars),
    )
