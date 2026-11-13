---
lens: design
statement: "Every fact has one owning read path and one owning write path; there is no file fallback, dual reader or shadow state."
read_when: "before adding a second reader, a cache or a fallback for any fact"
touches: [area/storage]
history:
  - {date: 2026-11-08, what: "recorded from the owner's single-path ruling"}
---
