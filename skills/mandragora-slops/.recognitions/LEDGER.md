# Learned recognition ledger

Append-only log of recognitions added by `python -m scanners.recognitions add`.
One row per learned recognition. Duplicates do not get a row; they raise HITS instead.
The date column is written by the script at run time.

| Date | ID | Input source | Reason |
|------|----|--------------|--------|
