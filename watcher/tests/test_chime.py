import pytest

from fakes import FakeDevice
from flights_watcher.chime import MutedLaunchDevice


class MutableDevice(FakeDevice):
    def __init__(self, muted: bool = False, launch_fails: bool = False) -> None:
        super().__init__()
        self.muted = muted
        self.launch_fails = launch_fails
        self.mutes: list[bool] = []
        self.muted_at_launch: bool | None = None

    def is_muted(self) -> bool:
        return self.muted

    def set_muted(self, muted: bool) -> None:
        self.muted = muted
        self.mutes.append(muted)

    def launch(self, app_id: str) -> None:
        self.muted_at_launch = self.muted
        if self.launch_fails:
            raise TimeoutError("no answer")
        super().launch(app_id)


def test_the_hub_is_muted_through_the_launch_and_the_chime():
    inner, pauses = MutableDevice(), []
    MutedLaunchDevice(inner, 3, pauses.append).launch("F50173D6")
    assert inner.muted_at_launch is True
    assert pauses == [3]
    assert inner.mutes == [True, False]


def test_the_sound_comes_back_when_the_launch_fails():
    inner = MutableDevice(launch_fails=True)
    with pytest.raises(TimeoutError):
        MutedLaunchDevice(inner, 3, lambda _seconds: None).launch("F50173D6")
    assert inner.muted is False


def test_a_hub_that_was_already_muted_stays_muted():
    inner = MutableDevice(muted=True)
    MutedLaunchDevice(inner, 3, lambda _seconds: None).launch("F50173D6")
    assert inner.mutes == []
    assert inner.launched == ["F50173D6"]


def test_everything_but_the_launch_goes_straight_to_the_hub():
    inner = MutableDevice()
    device = MutedLaunchDevice(inner, 3, lambda _seconds: None)
    inner.hidden = True
    device.send({"type": "card"})
    device.quit()
    assert device.running_app_id() == "E8C28D3C"
    assert device.is_idle() and device.is_hidden()
    assert inner.sent == [{"type": "card"}]
    assert inner.quits == 1
