# Security policy

## Threat model

testsniper parses repository source with Python's `ast` module and never
executes the code it analyzes. However, it then runs pytest, which does
execute the target project's code, exactly as running pytest yourself
would. Do not point testsniper at repositories you would not run pytest
in. It also shells out to `git` in the target repository, so repository
hooks configured there behave as they would for any git command.

## Supported versions

Only the latest release on `main` receives fixes.

## Reporting a vulnerability

Email andre.x.ruizloera@gmail.com with a description and reproduction
steps. Please do not open a public issue for security reports. You should
get a response within a week.
