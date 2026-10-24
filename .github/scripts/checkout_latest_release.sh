#!/bin/sh
# Checks out the latest release for the Read the Docs version `latest`, so that
# https://smalldi.readthedocs.io/en/latest/ documents the latest release instead of the head of master.
#
# Read the Docs runs this in the post_checkout job of .readthedocs.yaml, after cloning the commit it was asked to
# build. For the version `latest` the script fetches the tags, picks the highest release tag (MAJOR.MINOR.PATCH with
# an optional v prefix; pre-release tags don't count) and checks it out, so every later job stages and builds the
# pages and sources of that release. Any other version, a release tag or a pull request, builds the commit it was
# cloned at. When the latest release predates the documentation site, the build is cancelled with exit status 183,
# the cancel code of Read the Docs, which leaves the published `latest` as it is.
#
# Run from any directory. Without READTHEDOCS_VERSION=latest in the environment the script does nothing.
set -eu

if [ "${READTHEDOCS_VERSION:-}" != "latest" ]; then
    echo "version '${READTHEDOCS_VERSION:-}' builds the checked-out commit"
    exit 0
fi

cd "$(dirname "$0")/../.."
git fetch --quiet --depth 1 origin '+refs/tags/*:refs/tags/*'
release="$(git tag --list \
    | grep -E '^v?[0-9]+\.[0-9]+\.[0-9]+$' \
    | sed -E 's/^(v?)(.*)$/\2 \1\2/' \
    | sort -V \
    | tail -n 1 \
    | cut -d ' ' -f 2)"

if [ -z "$release" ]; then
    echo "no release tag to build the version latest from" >&2
    exit 1
fi
if ! git cat-file -e "$release:.readthedocs.yaml" 2>/dev/null; then
    echo "release $release predates the documentation site; the published latest stays as it is"
    exit 183
fi
git checkout --quiet --detach "$release"
echo "checked out release $release for the version latest"
