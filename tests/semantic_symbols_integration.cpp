#include <fcitx/addonmanager.h>
#include <fcitx/candidatelist.h>
#include <fcitx/inputcontext.h>
#include <fcitx/inputcontextmanager.h>
#include <fcitx/inputpanel.h>
#include <fcitx/instance.h>
#include <fcitx-utils/event.h>
#include <fcitx-utils/eventdispatcher.h>
#include <fcitx-module/testfrontend/testfrontend_public.h>
#include <cassert>
#include <iostream>

using namespace fcitx;

int main() {
    char arg0[] = "semantic-symbols-test";
    char arg1[] = "--disable=all";
    char arg2[] = "--enable=semantic-symbols,testfrontend";
    char *argv[] = {arg0, arg1, arg2};
    Instance instance(3, argv);
    instance.addonManager().registerDefaultLoader(nullptr);
    AddonInstance *frontend = nullptr;
    InputContext *ic = nullptr;
    ICUUID uuid{};
    int stage = 0;
    int ticks = 0;
    auto key = [&](const char *value) {
        return frontend->call<ITestFrontend::sendKeyEvent>(uuid, Key(value), false);
    };
    auto type = [&](const std::string &text) {
        for (char c : text) {
            std::string value(1, c);
            assert(key(c == ' ' ? "space" : value.c_str()));
        }
    };
    instance.eventDispatcher().schedule([&] {
        assert(instance.addonManager().addon("semantic-symbols"));
        frontend = instance.addonManager().addon("testfrontend");
        assert(frontend);
        uuid = frontend->call<ITestFrontend::createInputContext>("semantic-test");
        ic = instance.inputContextManager().findByUUID(uuid);
        ic->focusIn();
        ic->setCapabilityFlags(CapabilityFlag::Password);
        assert(!key("Control+Shift+U"));
        ic->setCapabilityFlags(CapabilityFlag::Preedit);
        ic->inputPanel().setPreedit(Text("unfinished"));
        assert(!key("Control+Shift+U"));
        ic->inputPanel().reset();
        assert(key("Control+Shift+U"));
        type("check marx");
        assert(key("BackSpace"));
        type("k");
        assert(ic->inputPanel().clientPreedit().toString() == "check mark");
        stage = 1;
    });
    auto timer = instance.eventLoop().addTimeEvent(CLOCK_MONOTONIC, now(CLOCK_MONOTONIC) + 20000, 0,
        [&](EventSourceTime *source, uint64_t) {
            assert(++ticks < 250);
            if (!stage) {
                source->setNextInterval(20000);
                source->setOneShot();
                return true;
            }
            auto candidates = ic->inputPanel().candidateList();
            if (stage == 1 && candidates && !candidates->empty()) {
                // Each candidate is a grid line of glyphs, unlabelled, with the
                // selection painted inside the line instead of on it.
                assert(candidates->size() == 3);
                assert(candidates->layoutHint() == CandidateLayoutHint::Vertical);
                assert(candidates->cursorIndex() == -1);
                assert(candidates->candidate(0).hasCustomLabel());
                assert(candidates->candidate(0).customLabel().toString().empty());
                assert(candidates->candidate(0).text().toString() == " ✓   1   2   3   4   5   6  ");
                assert(candidates->candidate(2).text().toString() == " 14   15  ");
                assert(candidates->candidate(0).text().stringAt(0) == " ✓  ");
                assert(candidates->candidate(0).text().formatAt(0).test(TextFormatFlag::HighLight));
                assert(!candidates->candidate(0).text().formatAt(1).test(TextFormatFlag::HighLight));
                assert(ic->inputPanel().auxDown().toString() == "result");
                // Down moves a whole row, Right one glyph; the name follows.
                assert(key("Down"));
                assert(ic->inputPanel().auxDown().toString() == "filler 7");
                assert(key("Right"));
                assert(ic->inputPanel().auxDown().toString() == "filler 8");
                assert(key("Up"));
                assert(key("Left"));
                assert(ic->inputPanel().auxDown().toString() == "result");
                // A single space extends the query; the popup keeps its glyphs.
                assert(key("space"));
                assert(ic->inputPanel().clientPreedit().toString() == "check mark ");
                assert(ic->inputPanel().candidateList() &&
                       !ic->inputPanel().candidateList()->empty());
                frontend->call<ITestFrontend::pushCommitExpectation>("✓");
                assert(key("space"));
                assert(ic->inputPanel().clientPreedit().toString().empty());
                assert(key("Control+Shift+U"));
                type("slow");
                assert(key("Escape"));
                assert(key("Control+Shift+U"));
                type("forever");
                stage = 2;
            } else if (stage == 2 && candidates && !candidates->empty()) {
                assert(candidates->candidate(0).text().stringAt(0) == " ∞  ");
                frontend->call<ITestFrontend::pushCommitExpectation>("∞");
                assert(key("Return"));
                assert(key("Control+Shift+U"));
                type("forever");
                stage = 4;
            } else if (stage == 4 && candidates && !candidates->empty()) {
                assert(key("Control+u"));
                assert(ic->inputPanel().clientPreedit().toString().empty());
                assert(!ic->inputPanel().candidateList() ||
                       ic->inputPanel().candidateList()->empty());
                type("slow");
                ic->focusOut();
                assert(ic->inputPanel().auxUp().empty());
                stage = 3;
                ticks = 0;
            } else if (stage == 3 && ticks > 20) {
                assert(ic->inputPanel().auxUp().empty());
                assert(!ic->inputPanel().candidateList());
                frontend->call<ITestFrontend::destroyInputContext>(uuid);
                // An application without preedit support keeps the query in
                // the panel instead, and never receives it as text.
                uuid = frontend->call<ITestFrontend::createInputContext>("no-preedit");
                ic = instance.inputContextManager().findByUUID(uuid);
                ic->focusIn();
                ic->setCapabilityFlags(CapabilityFlags());
                assert(key("Control+Shift+U"));
                type("a");
                assert(ic->inputPanel().auxUp().toString() == "a");
                assert(ic->inputPanel().clientPreedit().toString().empty());
                assert(key("Escape"));
                frontend->call<ITestFrontend::destroyInputContext>(uuid);
                instance.exit();
                std::cout << "Glyph grid, xy navigation, name preview, space commit, cancellation, "
                             "stale replies and privacy gates passed\n";
                return false;
            }
            source->setNextInterval(20000);
            source->setOneShot();
            return true;
        });
    return instance.exec();
}
