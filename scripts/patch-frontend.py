"""Keep fnOS sessions current after upstream site authentication and restarts."""
from pathlib import Path
import re
import sys

# Match behavior, including the distinction between explicit logout and the
# implicit reset used after site authentication/restart. Fail on upstream drift.
RESET = re.compile(
    r'function (\w+)\((\w+)=!1\)\{[^{}]{0,300}?'
    r'\2\?(\w+)\.logout\(\):\3\.resetSession\(\),'
    r'\w+\.reset\(\),\w+\.push\("/login"\)\}'
)
MARKER = '/* fnos-session-refresh */'
GUARD = re.compile(re.escape(MARKER) + r'if\(!\w+&&window\.MoviePilotFnos\?\.refreshSession\)'
                   r'\{window\.MoviePilotFnos\.refreshSession\(\);return\}')


def patch(public):
    matches = []
    for path in (public / 'assets').glob('default-*.js'):
        text = path.read_text(encoding='utf-8')
        text = GUARD.sub('', text)
        for match in RESET.finditer(text):
            matches.append((path, text, match))
    if len(matches) != 1:
        raise RuntimeError(f'Frontend session reset target changed: {len(matches)} matches')
    path, text, match = matches[0]
    argument = match.group(2)
    guard = (f'{MARKER}if(!{argument}&&window.MoviePilotFnos?.refreshSession)'
             '{window.MoviePilotFnos.refreshSession();return}')
    # A fresh match cannot contain braces in the prefix; insert after the first.
    start = text.index('{', match.start()) + 1
    path.write_text(text[:start] + guard + text[start:], encoding='utf-8', newline='\n')


if __name__ == '__main__':
    patch(Path(sys.argv[1]))
