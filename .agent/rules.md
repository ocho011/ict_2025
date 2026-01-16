# GitHub Issue Handling Rules

When the user asks to "solve" or "handle" a GitHub issue (e.g., "이슈 #11 해결해 줘"):

1. **Automatic Branch Creation**: Always create a new branch from `main` before starting work.
   - naming convention: `feat/issue-<number>` (e.g., `feat/issue-11`)
2. **Switch to Branch**: Immediately checkout the newly created branch.
3. **Notify User**: Inform the user that the branch has been created and switched to.
4. **Proceed with Task**: Start analyzing and implementing the solution on that branch.
