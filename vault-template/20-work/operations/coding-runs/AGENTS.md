# Coding run rules

- Treat `coding-run.json` as the durable state for one bounded coding run.
- Preserve exact repository revisions, context hashes, mode history, and evidence.
- Do not claim JIRA verification, tests, review, approval, or publication without
  recorded evidence.
- Do not launch an agent or mutate an external system from a run record alone.
- Keep assignment previews local until their branch, revision, context, and write
  scope pass validation.
