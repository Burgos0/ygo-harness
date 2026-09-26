# edison/scripts — override card scripts

Lua scripts here are checked **before** `data/CardScripts` (see `edison/provider.py`).
Name them exactly like the official file they replace (`c<passcode>.lua`, or a global such as
`utility.lua`). Official data in `data/` is never modified; delete a file here to fall back to it.
