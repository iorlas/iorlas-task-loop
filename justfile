# just test <feature>: run only that feature's tests (see tests/feature_tests.py); no argument = the whole suite
test feature="":
    python3 tests/feature_tests.py {{feature}}

# Install the exact tool versions recorded in mise.lock.
tools:
    MISE_IGNORED_CONFIG_PATHS=$HOME/.config/mise mise install --locked
