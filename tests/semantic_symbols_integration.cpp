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
        assert(!key("Control+Alt+u"));
        ic->setCapabilityFlags(CapabilityFlags());
        ic->inputPanel().setPreedit(Text("unfinished"));
        assert(!key("Control+Alt+u"));
        ic->inputPanel().reset();
        assert(key("Control+Alt+u"));
        type("check marx");
        assert(key("BackSpace"));
        type("k");
        assert(ic->inputPanel().auxUp().toString() == "Symbols: check mark");
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
                assert(candidates->candidate(0).text().toString() == "✓");
                assert(key("Down"));
                assert(key("Up"));
                frontend->call<ITestFrontend::pushCommitExpectation>("✓");
                assert(key("Return"));
                assert(ic->inputPanel().auxUp().empty());
                assert(key("Control+Alt+u"));
                type("slow");
                assert(key("Escape"));
                assert(key("Control+Alt+u"));
                type("forever");
                stage = 2;
            } else if (stage == 2 && candidates && !candidates->empty()) {
                assert(candidates->candidate(0).text().toString() == "∞");
                assert(key("Control+u"));
                assert(ic->inputPanel().auxUp().toString() == "Symbols: ");
                type("slow");
                ic->focusOut();
                assert(ic->inputPanel().auxUp().empty());
                stage = 3;
                ticks = 0;
            } else if (stage == 3 && ticks > 20) {
                assert(ic->inputPanel().auxUp().empty());
                assert(!ic->inputPanel().candidateList());
                frontend->call<ITestFrontend::destroyInputContext>(uuid);
                instance.exit();
                std::cout << "Native popup, insertion, cancellation, stale replies and privacy gates passed\n";
                return false;
            }
            source->setNextInterval(20000);
            source->setOneShot();
            return true;
        });
    return instance.exec();
}
