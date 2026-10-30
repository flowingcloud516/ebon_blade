import unittest

from basic_connector.bmc_connector import (
    BiosSnapshot,
    BmcConnector,
    BmcUnsupportedActionError,
    IssuePolicy,
    PowerAction,
    PowerActionReceipt,
    PowerOperationStatus,
    PowerState,
)


class FakeBmcBackend:
    backend_name = "fake"

    def __init__(self, states, *, issue_error=None, accepted=True):
        self.states = list(states)
        self.issue_error = issue_error
        self.accepted = accepted
        self.actions = []
        self.closed = False

    async def get_power_state(self):
        if len(self.states) > 1:
            return self.states.pop(0)
        return self.states[0]

    async def issue_power_action(self, action):
        self.actions.append(action)
        if self.issue_error is not None:
            raise self.issue_error
        return PowerActionReceipt(self.accepted, "fake receipt")

    async def read_all_bios_config(self):
        return BiosSnapshot("system-1", {"Example": "Value"}, self.backend_name)

    async def close(self):
        self.closed = True


class BmcConnectorTests(unittest.IsolatedAsyncioTestCase):
    async def test_if_needed_skips_action_when_target_is_already_satisfied(self):
        backend = FakeBmcBackend([PowerState.OFF])
        connector = BmcConnector(backend, poll_interval=0)
        result = await connector.force_off()
        self.assertTrue(result.succeeded)
        self.assertFalse(result.action_issued)
        self.assertFalse(result.changed)
        self.assertEqual(backend.actions, [])

    async def test_always_issues_action_even_when_already_at_target(self):
        backend = FakeBmcBackend([PowerState.OFF, PowerState.OFF])
        connector = BmcConnector(backend, poll_interval=0)
        result = await connector.force_off(issue_policy=IssuePolicy.ALWAYS)
        self.assertTrue(result.succeeded)
        self.assertTrue(result.action_issued)
        self.assertTrue(result.verified)
        self.assertFalse(result.changed)
        self.assertEqual(backend.actions, [PowerAction.FORCE_OFF])

    async def test_action_is_verified_by_polling_final_state(self):
        backend = FakeBmcBackend([PowerState.OFF, PowerState.OFF, PowerState.ON])
        connector = BmcConnector(backend, transition_timeout=1, poll_interval=0)
        result = await connector.power_on()
        self.assertEqual(result.status, PowerOperationStatus.SUCCEEDED)
        self.assertEqual(result.final_state, PowerState.ON)
        self.assertTrue(result.changed)
        self.assertEqual(backend.actions, [PowerAction.POWER_ON])

    async def test_issue_exception_is_unknown_and_never_replayed(self):
        backend = FakeBmcBackend([PowerState.ON], issue_error=OSError("lost"))
        connector = BmcConnector(backend, poll_interval=0)
        result = await connector.force_off(issue_policy=IssuePolicy.ALWAYS)
        self.assertEqual(result.status, PowerOperationStatus.UNKNOWN)
        self.assertIsNone(result.action_accepted)
        self.assertEqual(backend.actions, [PowerAction.FORCE_OFF])
        self.assertNotIn("lost", result.diagnostic_summary)

    async def test_unsupported_and_rejected_actions_are_explicit(self):
        unsupported = FakeBmcBackend(
            [PowerState.ON], issue_error=BmcUnsupportedActionError("not supported")
        )
        result = await BmcConnector(unsupported, poll_interval=0).force_off(
            issue_policy=IssuePolicy.ALWAYS
        )
        self.assertEqual(result.status, PowerOperationStatus.UNSUPPORTED)

        rejected = FakeBmcBackend([PowerState.ON], accepted=False)
        result = await BmcConnector(rejected, poll_interval=0).force_off(
            issue_policy=IssuePolicy.ALWAYS
        )
        self.assertEqual(result.status, PowerOperationStatus.FAILED)
        self.assertFalse(result.action_accepted)

    async def test_bios_snapshot_and_close_delegate_to_backend(self):
        backend = FakeBmcBackend([PowerState.ON])
        connector = BmcConnector(backend)
        snapshot = await connector.read_all_bios_config()
        self.assertEqual(snapshot.attributes["Example"], "Value")
        await connector.close()
        self.assertTrue(backend.closed)


if __name__ == "__main__":
    unittest.main()
