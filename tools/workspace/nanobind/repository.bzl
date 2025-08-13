load("//tools/workspace:github.bzl", "github_archive")

def nanobind_repository(
        name,
        mirrors = None):
    github_archive(
        name = name,
        repository = "wjacob/nanobind",
        commit = "v2.8.0",
        sha256 = "FOOBAR",
        build_file = ":package.BUILD.bazel",
        mirrors = mirrors,
    )
