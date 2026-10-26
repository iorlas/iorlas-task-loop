# just test <feature>: run only that feature's tests (see tests/feature_tests.py); no argument = the whole suite
test feature="":
    python3 tests/feature_tests.py {{feature}}
