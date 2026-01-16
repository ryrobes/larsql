#!/bin/bash
#
# Release script for larsql
# Usage: ./scripts/release.sh [patch|minor|major]
#
# This script:
# 1. Bumps the version in pyproject.toml
# 2. Commits the version change
# 3. Creates a git tag
# 4. Pushes to GitHub (which triggers PyPI publish via GitHub Actions)
#

set -e

cd "$(dirname "$0")/.."

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Check for uncommitted changes
if [[ -n $(git status --porcelain) ]]; then
    echo -e "${RED}Error: You have uncommitted changes. Please commit or stash them first.${NC}"
    git status --short
    exit 1
fi

# Get bump type (default: patch)
BUMP_TYPE=${1:-patch}

if [[ ! "$BUMP_TYPE" =~ ^(patch|minor|major)$ ]]; then
    echo -e "${RED}Error: Invalid bump type '$BUMP_TYPE'. Use: patch, minor, or major${NC}"
    exit 1
fi

# Get current version from pyproject.toml
CURRENT_VERSION=$(grep -E '^version = ' lars/pyproject.toml | sed 's/version = "\(.*\)"/\1/')
echo -e "${YELLOW}Current version: ${CURRENT_VERSION}${NC}"

# Parse version components
IFS='.' read -r MAJOR MINOR PATCH <<< "$CURRENT_VERSION"

# Bump version
case $BUMP_TYPE in
    major)
        MAJOR=$((MAJOR + 1))
        MINOR=0
        PATCH=0
        ;;
    minor)
        MINOR=$((MINOR + 1))
        PATCH=0
        ;;
    patch)
        PATCH=$((PATCH + 1))
        ;;
esac

NEW_VERSION="${MAJOR}.${MINOR}.${PATCH}"
echo -e "${GREEN}New version: ${NEW_VERSION}${NC}"

# Confirm
read -p "Release v${NEW_VERSION}? [y/N] " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Aborted."
    exit 1
fi

# Update version in pyproject.toml
sed -i "s/^version = \"${CURRENT_VERSION}\"/version = \"${NEW_VERSION}\"/" lars/pyproject.toml

# Verify the change
VERIFY_VERSION=$(grep -E '^version = ' lars/pyproject.toml | sed 's/version = "\(.*\)"/\1/')
if [[ "$VERIFY_VERSION" != "$NEW_VERSION" ]]; then
    echo -e "${RED}Error: Version update failed${NC}"
    git checkout lars/pyproject.toml
    exit 1
fi

# Commit and tag
git add lars/pyproject.toml
git commit -m "Release v${NEW_VERSION}"
git tag "v${NEW_VERSION}"

echo -e "${GREEN}Created commit and tag v${NEW_VERSION}${NC}"

# Push
read -p "Push to GitHub (triggers PyPI publish)? [y/N] " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    git push && git push --tags
    echo -e "${GREEN}Pushed! GitHub Actions will publish to PyPI.${NC}"
    echo -e "Watch progress at: https://github.com/ryrobes/larsql/actions"
else
    echo -e "${YELLOW}Not pushed. Run manually:${NC}"
    echo "  git push && git push --tags"
fi
