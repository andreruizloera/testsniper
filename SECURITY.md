# Security policy

## Threat model

testsniper parses repository source with Python's `ast` module and never
executes the code it analyzes. However, it then runs pytest, which does
execute the target project's code, exactly as running pytest yourself
would. Do not point testsniper at repositories you would not run pytest
in. It also shells out to `git` in the target repository, so repository
hooks configured there behave as they would for any git command.

`pytest --testsniper-plan PATH` reads a selection plan. A plan is data
only: it is parsed with `json`, never evaluated, and a file that is not a
plan of the expected version is rejected with an error rather than
partially applied. A plan can still only remove tests from a run, so an
untrusted one is a denial-of-coverage risk, not a code-execution one.
Treat a plan with the same care as any other CI input that decides what
gets checked.

## Supported versions

Only the latest release on `main` receives fixes.

## Reporting a vulnerability

Email andre.x.ruizloera@gmail.com with a description and reproduction
steps. Please do not open a public issue for security reports. You should
get a response within a week.
