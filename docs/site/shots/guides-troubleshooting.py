# SPDX-License-Identifier: GPL-3.0-or-later
"""Screenshots for the Troubleshooting guide."""

from tests.docshots.spec import Shot, Until, popup, say, sidebar


def key_refused(stage):
    """A turn the API refuses: nothing changed, so it folds, and the box
    says what to do about the key."""
    stage.crate()
    script = stage.script("key_refused", [
        {"steps": [say("Looking at the crate first.")],
         "finish": {"subtype": "error_during_execution", "is_error": True, "result": "Invalid API key"}},
    ])
    yield from stage.turns(["Add a lid."], script)


def offline(stage):
    """The real start path with Online Access off: it stops before anything
    runs, which is what makes a fake key safe here."""
    import bpy

    from whittle.addon import operators

    if bpy.app.online_access:
        raise RuntimeError("this shot must never run with Online Access on")
    stage.crate()
    stage.preferences.api_key = "not-a-real-key"
    stage.props.prompt = "Add a lid."
    try:
        stage.run(operators.submit_sketch)
    except RuntimeError:
        pass
    yield Until(lambda: stage.ctl is not None and stage.ctl.process.state == "failed", "the start to fail")


SHOTS = [
    Shot("setup-needed", "No agent environment: the box offers Set Up.", scenario="setup_needed"),
    Shot("key-needed", "No API key: the box asks for one and the prompt stays.", scenario="key_needed"),
    Shot("key-refused", "A refused API key: a red line, a folded turn with Retry.", sidebar(), setup=key_refused),
    Shot("crashed", "The agent crashed: the box offers Restart and Retry.", scenario="crashed"),
    Shot("crash-reason", "The agent popover gives the crash's reason.", popup(panel="WHITTLE_PT_agent"),
         scenario="crashed"),
    Shot("could-not-start", "Online Access off: the box says Claude could not start.", sidebar(), setup=offline),
    Shot("online-reason", "The agent popover says to allow Online Access.", popup(panel="WHITTLE_PT_agent"),
         setup=offline),
    Shot("failed-turn", "A recovered tool error, then a failed turn with Retry.", scenario="error_turn"),
    Shot("folded-failure", "A failed turn that changed nothing, shown once with Retry.", scenario="folded_failure"),
]
