#include <fcitx/addonfactory.h>
#include <fcitx/addonmanager.h>
#include <fcitx/candidatelist.h>
#include <fcitx/inputcontext.h>
#include <fcitx/inputpanel.h>
#include <fcitx/instance.h>
#include <fcitx/tempmode.h>
#include <fcitx/tempmodemanager.h>
#include <fcitx/userinterface.h>
#include <fcitx-utils/capabilityflags.h>
#include <fcitx-utils/eventdispatcher.h>
#include <sys/socket.h>
#include <sys/un.h>
#include <unistd.h>
#include <condition_variable>
#include <cstdlib>
#include <cstring>
#include <functional>
#include <mutex>
#include <sstream>
#include <thread>

namespace {
using namespace fcitx;
using Rows = std::vector<std::pair<std::string, std::string>>;

struct Result {
    Rows rows;
    std::string error;
};

Result lookup(const std::string &query) {
    const char *runtime = std::getenv("XDG_RUNTIME_DIR");
    if (!runtime) {
        return {{}, "No user runtime directory"};
    }
    const std::string path = std::string(runtime) + "/fcitx5-semantic-symbols/search.sock";
    sockaddr_un address{};
    address.sun_family = AF_UNIX;
    if (path.size() >= sizeof(address.sun_path)) {
        return {{}, "Search socket path too long"};
    }
    std::memcpy(address.sun_path, path.c_str(), path.size() + 1);
    int fd = socket(AF_UNIX, SOCK_STREAM | SOCK_CLOEXEC, 0);
    if (fd < 0) {
        return {{}, "Cannot open search socket"};
    }
    struct SocketGuard {
        int fd;
        ~SocketGuard() { close(fd); }
    } guard{fd};
    timeval timeout{2, 0};
    setsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, &timeout, sizeof(timeout));
    setsockopt(fd, SOL_SOCKET, SO_SNDTIMEO, &timeout, sizeof(timeout));
    if (connect(fd, reinterpret_cast<sockaddr *>(&address), sizeof(address)) < 0) {
        return {{}, "Start fcitx5-semantic-symbols.service"};
    }
    auto request = query + "\n";
    size_t sent = 0;
    while (sent < request.size()) {
        auto n = send(fd, request.data() + sent, request.size() - sent, MSG_NOSIGNAL);
        if (n <= 0) {
            return {{}, "Search service unavailable"};
        }
        sent += static_cast<size_t>(n);
    }
    std::string response;
    char buffer[4096];
    while (response.size() < 16384) {
        auto n = recv(fd, buffer, sizeof(buffer), 0);
        if (n == 0) {
            break;
        }
        if (n < 0) {
            return {{}, "Search timed out; try again"};
        }
        response.append(buffer, static_cast<size_t>(n));
    }
    if (response.size() >= 16384) {
        return {{}, "Invalid search response"};
    }
    Rows rows;
    std::istringstream stream(response);
    std::string line;
    while (rows.size() < 18 && std::getline(stream, line)) {
        auto tab = line.find('\t');
        if (tab != std::string::npos && tab > 0) {
            rows.emplace_back(line.substr(0, tab), line.substr(tab + 1));
        }
    }
    return {std::move(rows), {}};
}

struct State {
    std::string query;
    uint64_t generation = 0;
    Rows rows;
    std::string status;
};

class SymbolCandidate : public CandidateWord {
public:
    SymbolCandidate(std::string glyph, std::string label,
                    std::function<void(InputContext *, std::string)> commit)
        : CandidateWord(Text(glyph)), glyph_(std::move(glyph)), commit_(std::move(commit)) {
        // The name belongs on the preview line, not next to every glyph.
        FCITX_UNUSED(label);
        setCustomLabel(Text());
    }
    void select(InputContext *ic) const override {
        auto commit = commit_;
        auto glyph = glyph_;
        commit(ic, std::move(glyph));
    }
private:
    std::string glyph_;
    std::function<void(InputContext *, std::string)> commit_;
};

class SemanticSymbols : public AddonInstance, public SimpleTempMode<State> {
public:
    explicit SemanticSymbols(Instance *instance) : instance_(instance) {
        dispatcher_.attach(&instance_->eventLoop());
        instance_->tempModeManager().registerTempMode(*this);
        worker_ = std::thread([this] {
            std::unique_lock lock(mutex_);
            while (true) {
                ready_.wait(lock, [this] { return stopping_ || pending_; });
                if (stopping_) {
                    return;
                }
                auto query = std::move(query_);
                auto reply = std::move(reply_);
                pending_ = false;
                lock.unlock();
                auto result = lookup(query);
                dispatcher_.schedule([reply = std::move(reply), result = std::move(result)]() mutable {
                    reply(std::move(result));
                });
                lock.lock();
            }
        });
    }

    ~SemanticSymbols() override {
        unregister();
        {
            std::lock_guard lock(mutex_);
            stopping_ = true;
        }
        ready_.notify_one();
        worker_.join();
        dispatcher_.detach();
    }

    std::string_view name() const override { return "semantic-symbols"; }

    bool triggerTempMode(const KeyEvent &event) override {
        auto *ic = event.inputContext();
        if (event.isRelease() || !event.key().check(Key("Control+Shift+U")) ||
            ic->capabilityFlags().testAny(CapabilityFlag::PasswordOrSensitive)) {
            return false;
        }
        // Never discard an unfinished Rime composition.
        if (!ic->inputPanel().preedit().empty() || !ic->inputPanel().clientPreedit().empty()) {
            return false;
        }
        auto *state = property(ic);
        state->query.clear();
        state->rows.clear();
        state->status = "Describe an emoji or symbol";
        ++state->generation;
        state->setActive(true);
        show(ic);
        return true;
    }

    void reset(InputContext *ic) override {
        auto *state = property(ic);
        if (state) {
            ++state->generation;
            state->query.clear();
            state->rows.clear();
            state->status.clear();
            state->setActive(false);
        }
        ic->inputPanel().reset();
        ic->updatePreedit();
        ic->updateUserInterface(UserInterfaceComponent::InputPanel);
    }

    bool keyEvent(const KeyEvent &event) override {
        if (event.isRelease()) {
            return true;
        }
        auto *ic = event.inputContext();
        auto *state = property(ic);
        const auto key = event.key();
        if (key.check(FcitxKey_Escape) || key.check(Key("Control+Shift+U"))) {
            reset(ic);
            return true;
        }
        auto candidates = ic->inputPanel().candidateList();
        // A trailing space is inert for the search, so the second one commits
        // while multi-word queries keep their separators.
        const bool spaceCommits =
            key.check(FcitxKey_space) && !state->query.empty() && state->query.back() == ' ';
        if (key.check(FcitxKey_Return) || key.check(FcitxKey_KP_Enter) || spaceCommits) {
            if (candidates && !candidates->empty() && candidates->cursorIndex() >= 0) {
                candidates->candidate(candidates->cursorIndex()).select(ic);
            }
            return true;
        }
        if (key.check(FcitxKey_Right) || key.check(FcitxKey_Left) || key.check(FcitxKey_Down) ||
            key.check(FcitxKey_Up) || key.check(FcitxKey_Tab) || key.check(Key("Shift+Tab"))) {
            if (candidates && candidates->toCursorMovable()) {
                if (key.check(FcitxKey_Left) || key.check(FcitxKey_Up) || key.check(Key("Shift+Tab"))) {
                    candidates->toCursorMovable()->prevCandidate();
                } else {
                    candidates->toCursorMovable()->nextCandidate();
                }
                showHeader(ic);
                ic->updateUserInterface(UserInterfaceComponent::InputPanel);
            }
            return true;
        }
        if (key.check(FcitxKey_Page_Up) || key.check(FcitxKey_Page_Down)) {
            if (candidates && candidates->toPageable()) {
                auto *pages = candidates->toPageable();
                if (key.check(FcitxKey_Page_Up) && pages->hasPrev()) { pages->prev(); }
                if (key.check(FcitxKey_Page_Down) && pages->hasNext()) { pages->next(); }
                showHeader(ic);
                ic->updateUserInterface(UserInterfaceComponent::InputPanel);
            }
            return true;
        }
        if (key.check(FcitxKey_BackSpace)) {
            if (!state->query.empty()) {
                auto pos = state->query.size() - 1;
                while (pos && (static_cast<unsigned char>(state->query[pos]) & 0xc0) == 0x80) { --pos; }
                state->query.erase(pos);
            }
        } else if (key.check(Key("Control+U"))) {
            state->query.clear();
        } else {
            if (!key.isSimple()) {
                return true;
            }
            auto text = Key::keySymToUTF8(key.sym());
            if (text.empty() || static_cast<unsigned char>(text[0]) < 0x20 || text[0] == 0x7f ||
                state->query.size() + text.size() > 256) {
                return true;
            }
            state->query += text;
        }
        auto generation = ++state->generation;
        if (state->query.empty()) {
            state->rows.clear();
            state->status = "Describe an emoji or symbol";
            show(ic);
        } else {
            // Keep the previous glyphs on screen: replacing them with an empty
            // list for the few milliseconds of a lookup is what flickers.
            showHeader(ic);
            ic->updateUserInterface(UserInterfaceComponent::InputPanel);
        }
        if (!state->query.empty()) {
            auto ref = ic->watch();
            std::lock_guard lock(mutex_);
            query_ = state->query;
            reply_ = [this, ref, generation](Result result) {
                auto *context = ref.get();
                if (!context) { return; }
                auto *current = property(context);
                if (!current->isActive() || current->generation != generation) { return; }
                current->rows = std::move(result.rows);
                current->status = result.error.empty() ? "Space or Enter inserts; Esc cancels" : result.error;
                show(context);
            };
            pending_ = true;
            ready_.notify_one();
        }
        return true;
    }

private:
    // One reserved line: the typed query, then the highlighted glyph's name.
    void showHeader(InputContext *ic) {
        auto *state = property(ic);
        auto &panel = ic->inputPanel();
        std::string name = state->status;
        auto candidates = panel.candidateList();
        if (candidates && candidates->toBulkCursor()) {
            auto index = candidates->toBulkCursor()->globalCursorIndex();
            if (index >= 0 && static_cast<size_t>(index) < state->rows.size()) {
                name = state->rows[index].second;
            }
        }
        panel.setAuxUp(Text(state->query));
        panel.setAuxDown(Text(std::move(name)));
    }

    void show(InputContext *ic) {
        auto *state = property(ic);
        auto &panel = ic->inputPanel();
        auto list = std::make_unique<CommonCandidateList>();
        list->setPageSize(14);
        list->setLayoutHint(CandidateLayoutHint::Horizontal);
        for (const auto &[glyph, label] : state->rows) {
            list->append<SymbolCandidate>(glyph, label, [this](InputContext *context, std::string value) {
                reset(context);
                context->commitString(value);
            });
        }
        list->setGlobalCursorIndex(state->rows.empty() ? -1 : 0);
        panel.setCandidateList(std::move(list));
        showHeader(ic);
        ic->updateUserInterface(UserInterfaceComponent::InputPanel);
    }

    Instance *instance_;
    EventDispatcher dispatcher_;
    std::thread worker_;
    std::mutex mutex_;
    std::condition_variable ready_;
    bool pending_ = false;
    bool stopping_ = false;
    std::string query_;
    std::function<void(Result)> reply_;
};

class Factory : public AddonFactory {
    AddonInstance *create(AddonManager *manager) override {
        return new SemanticSymbols(manager->instance());
    }
};
} // namespace

FCITX_ADDON_FACTORY(Factory)
