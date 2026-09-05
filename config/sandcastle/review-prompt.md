# Independent review

You are the second agent on this branch. Another agent wrote the code that is
already committed here. Your job is to review it, not to rewrite it.

## What to do

1. Read the diff of this branch against the commit it started from:

   ```bash
   git log --oneline @{u}..HEAD 2>/dev/null || git log --oneline -10
   git diff HEAD~1 2>/dev/null || git diff
   ```

2. Judge the change against the repository's own standards. Read `AGENTS.md`
   or `CLAUDE.md` if the repository has one, and follow it.

3. Look for these, in this order:
   - a defect that makes the code do the wrong thing
   - a missing or wrong test
   - a violation of a documented rule of this repository
   - dead code, or code that repeats something that already exists

4. Fix only what is wrong. Commit each fix with a message that says what was
   wrong. Do not reformat code that works. Do not add a feature.

5. If the change is correct, make no commit and say so.

## Rules

- Stay on this branch. Do not create another branch.
- Do not push. Do not open a pull request. Do not merge.
- Do not change the version control history that is already here.

When you are done, write `<promise>COMPLETE</promise>`.
