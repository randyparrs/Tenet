# Notice

Tenet includes or builds on the following third-party work.

## Lacre

- Source: https://github.com/eudomar500/lacre
- License: MIT, Copyright (c) 2026 Insidr Labs
- What Tenet uses: the deployed Lacre contracts on GenLayer Bradbury (Router, Verifier and KeyCache)
  for DKIM email attestations, and two files copied unchanged into `arbiter/lacre_vendor/`
  (`lacre/dkimcore.py` and `lacre/dkimbody.py`, commit d2cb1fc1b19b9b31af7ef1b561221f447ec21838).
  The full license text is in `arbiter/lacre_vendor/LICENSE`.

## Solidity libraries

- OpenZeppelin Contracts 5.6.1 (`evm/lib/openzeppelin-contracts`, git submodule), MIT license.
- Forge Standard Library 1.16.2 (`evm/lib/forge-std`, git submodule), MIT or Apache 2.0 license.
