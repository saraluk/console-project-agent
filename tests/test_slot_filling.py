from fakes import P


def test_create_asks_for_both_then_each_missing_field(bot, parser, repo):
    parser.script.update(
        {
            "new project in Bangkok starting Dec 1": P(
                "create", location="Bangkok", start_date="2026-12-01"
            ),
            "it's called Office Fit-out": P("provide_info", project_name="Office Fit-out"),
            "Siam Corp": P("provide_info", customer="Siam Corp"),
        }
    )

    reply = bot.handle("new project in Bangkok starting Dec 1")
    assert "project name" in reply and "customer" in reply
    assert repo.list_all() == []

    reply = bot.handle("it's called Office Fit-out")
    assert "Who is the customer?" in reply
    assert repo.list_all() == []

    reply = bot.handle("Siam Corp")
    # The LLM was told what we were waiting for, so the bare reply could be understood.
    assert "just asked the user for: customer" in parser.calls[-1][1]
    assert reply == 'Done. Created project "Office Fit-out" for customer Siam Corp '\
        "(start: 2026-12-01, location: Bangkok)."
    [project] = repo.list_all()
    assert (project.project_name, project.customer, project.location, project.start_date) == (
        "Office Fit-out",
        "Siam Corp",
        "Bangkok",
        "2026-12-01",
    )
    assert bot.state["draft"] is None and bot.state["awaiting"] is None


def test_context_tells_llm_what_was_asked(bot, parser):
    parser.script["new project Apollo"] = P("create", project_name="Apollo")
    bot.handle("new project Apollo")
    bot.handle("Acme")
    context = parser.calls[-1][1]
    assert "Apollo" in context and "just asked the user for: customer" in context


def test_complete_request_saves_immediately(bot, parser, repo):
    parser.script["add Apollo for Acme, status in progress"] = P(
        "create", project_name="Apollo", customer="Acme", status="in progress"
    )
    reply = bot.handle("add Apollo for Acme, status in progress")
    assert reply == 'Done. Created project "Apollo" for customer Acme (status: active).'
    assert repo.get("P-001").status == "active"


def test_other_command_mid_draft_keeps_draft_and_reminds(bot, parser, repo):
    parser.script.update(
        {
            "new project Apollo": P("create", project_name="Apollo"),
            "Acme": P("provide_info", customer="Acme"),
        }
    )
    bot.handle("new project Apollo")
    reply = bot.handle("list")
    assert "You don't have any projects yet" in reply
    assert 'unfinished project "Apollo", missing: customer' in reply
    assert bot.state["awaiting"] == "fields"

    assert bot.handle("Acme").startswith('Done. Created project "Apollo"')


def test_cancel_discards_draft(bot, parser, repo):
    parser.script["new project Apollo"] = P("create", project_name="Apollo")
    bot.handle("new project Apollo")
    assert "discarded" in bot.handle("cancel")
    assert bot.state["draft"] is None
    assert "Nothing to cancel" in bot.handle("cancel")


def test_invalid_date_is_dropped_with_explanation(bot, parser, repo):
    parser.script["Apollo for Acme starting someday"] = P(
        "create", project_name="Apollo", customer="Acme", start_date="someday"
    )
    reply = bot.handle("Apollo for Acme starting someday")
    assert "couldn't read 'someday' as a date" in reply
    assert repo.get("P-001").start_date is None


def test_new_create_with_different_name_replaces_draft(bot, parser):
    parser.script.update(
        {
            "new project Apollo": P("create", project_name="Apollo"),
            "new project Zeus for Globex": P("create", project_name="Zeus", customer="Globex"),
        }
    )
    bot.handle("new project Apollo")
    reply = bot.handle("new project Zeus for Globex")
    assert '"Apollo" was discarded' in reply and 'Created project "Zeus"' in reply


def test_llm_down_keeps_draft(bot, parser, repo):
    parser.script["new project Apollo"] = P("create", project_name="Apollo")
    bot.handle("new project Apollo")
    parser.down = True
    reply = bot.handle("Acme")
    assert "couldn't reach" in reply and 'unfinished project "Apollo"' in reply
    assert bot.state["draft"] == {"project_name": "Apollo"}
    # Fixed words still work without the LLM.
    assert "discarded" in bot.handle("cancel")


def test_duplicate_name_warns_but_saves(bot, parser, repo):
    parser.script["Apollo for Acme"] = P("create", project_name="Apollo", customer="Acme")
    bot.handle("Apollo for Acme")
    reply = bot.handle("Apollo for Acme")
    assert reply.startswith('Done. Created project "Apollo"')
    assert 'more than one project named "Apollo"' in reply
    assert "P-00" not in reply
    assert len(repo.list_all()) == 2
