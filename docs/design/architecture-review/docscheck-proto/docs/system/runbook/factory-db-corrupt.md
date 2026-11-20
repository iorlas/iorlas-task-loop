---
# Status: evidence; historical format specimen, not current system authority
when: "factory.db fails at start as corrupt or mismatched."
actor: persona/owner
touches: [area/storage, workflow/factory-start, external/tracker]
steps:
  - {do: "stop the rounds process and read the outcome and its message", expect: "no write reached factory.db"}
  - {do: "hand the file to the repair agent through a blocked task carrying a repair prompt", expect: "the repair agent reports repaired or unrepairable"}
  - {do: "move factory.db aside when the repair agent reports unrepairable, then run tl slot adopt", expect: "work is re-derived from Git and [[external/tracker]] by [[workflow/factory-start]]"}
---
