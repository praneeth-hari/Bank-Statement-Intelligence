"""Ask questions of approved statements in plain language, without ever letting a model write code.

A question becomes a small, validated ``Query`` (what to add up, over which dates, for which kind of transaction).
Plain Python then runs it over the corrected rows. Whoever produced the ``Query`` - a rule or a model - never
touches the data, and every answer comes with the rows it was computed from.
"""
