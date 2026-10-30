# Contributing

This is an early-stage project. Contributions will be welcomed once the repository is made public and the contribution process is finalised.

When proposing changes, preserve the chart-first, minimalist, no-gradient design; keep features optional rather than filling the main screen with controls. Open an issue before large architectural work, and check [the master plan](docs/PLAN.md) first. Avoid adding trackers, API keys or restrictive dependencies.

## Licence and CLA

OpenChart AI is licensed under the [GNU AGPLv3](LICENSE). Before your first pull request can be merged you must sign the [Contributor Licence Agreement](CLA.md); the CLA Assistant bot will ask you to on the pull request. You keep the copyright in your work.

New source files start with an SPDX licence header, using the comment style of the language:

```
SPDX-License-Identifier: AGPL-3.0-or-later
```

The project names and logos are covered by the [trademark policy](TRADEMARKS.md), not the AGPL.

## Checks

Run `python3 -m unittest discover -s tests -v` before submitting any code changes.
