"""Seam.survivors: the one place that says which pids outlived a call's stop (the engine reads no pid itself)."""
from taskloop.adapters.runner import Seam
from tlkernel.delegate import DelegateResult, Survivor, WorkerEnd


def test_no_stop_no_survivors():
    assert Seam().survivors() == []


def test_the_stops_own_finding_and_the_answers_merge_without_repeats():
    seam = Seam()
    seam.stop = {"alive": [4242]}
    res = DelegateResult(worker=WorkerEnd(end="worker_survived", survivors=[Survivor(pid=4242), Survivor(pid=7)]))
    assert seam.survivors(res) == [4242, 7]


def test_an_answer_without_a_worker_adds_none():
    assert Seam().survivors(DelegateResult()) == []
