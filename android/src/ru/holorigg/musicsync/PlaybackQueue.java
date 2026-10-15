package ru.holorigg.musicsync;

import java.util.*;

/** Small deterministic queue state machine. IDs remain in Store order; shuffle traversal is separate. */
final class PlaybackQueue {
    private final Random random;
    private final List<String> ordered = new ArrayList<>();
    private final List<String> history = new ArrayList<>();
    private final List<String> bag = new ArrayList<>();
    private boolean shuffle;
    private int historyIndex = -1;
    private String current = "";

    PlaybackQueue() { this(new Random()); }
    PlaybackQueue(Random random) { this.random = random; }

    void setQueue(List<String> ids, String current) {
        ordered.clear();
        if (ids != null) for (String id : ids) if (id != null && !id.isEmpty() && !ordered.contains(id)) ordered.add(id);
        this.current = current == null ? "" : current;
        history.clear(); historyIndex = -1; bag.clear();
        if (shuffle && ordered.contains(this.current)) { history.add(this.current); historyIndex = 0; refillBag(false); }
    }

    void setCurrent(String id) { current = id == null ? "" : id; }
    void setShuffle(boolean enabled) {
        if (shuffle == enabled) return;
        shuffle = enabled; history.clear(); bag.clear(); historyIndex = -1;
        if (shuffle && ordered.contains(current)) { history.add(current); historyIndex = 0; refillBag(false); }
    }
    boolean isShuffle() { return shuffle; }
    List<String> ids() { return new ArrayList<>(ordered); }
    int size() { return ordered.size(); }
    boolean canNext(boolean repeatAll) {
        if (ordered.isEmpty()) return false;
        if (shuffle) return historyIndex + 1 < history.size() || !bag.isEmpty() || repeatAll;
        int i = ordered.indexOf(current);
        return i >= 0 ? i + 1 < ordered.size() || repeatAll : true;
    }
    boolean canPrevious(boolean repeatAll) {
        if (ordered.isEmpty()) return false;
        if (shuffle) return historyIndex > 0;
        int i = ordered.indexOf(current);
        return i > 0 || repeatAll;
    }

    String next(boolean repeatAll) {
        if (ordered.isEmpty()) return null;
        if (!shuffle) {
            int i = ordered.indexOf(current);
            if (i < 0) return ordered.get(0);
            if (i + 1 < ordered.size()) return ordered.get(i + 1);
            return repeatAll ? ordered.get(0) : null;
        }
        if (historyIndex + 1 < history.size()) return history.get(++historyIndex);
        if (bag.isEmpty()) {
            if (!repeatAll) return null;
            if (ordered.size() == 1) return ordered.get(0);
            refillBag(true);
        }
        if (bag.isEmpty()) return null;
        String id = bag.remove(0);
        while (history.size() > historyIndex + 1) history.remove(history.size() - 1);
        history.add(id); historyIndex = history.size() - 1;
        return id;
    }

    String previous(boolean repeatAll) {
        if (ordered.isEmpty()) return null;
        if (shuffle) {
            if (historyIndex > 0) return history.get(--historyIndex);
            return null;
        }
        int i = ordered.indexOf(current);
        if (i > 0) return ordered.get(i - 1);
        return repeatAll ? ordered.get(ordered.size() - 1) : null;
    }

    void accepted(String id) {
        current = id == null ? "" : id;
        if (shuffle && !ordered.contains(current)) { ordered.add(current); history.clear(); historyIndex = -1; bag.clear(); history.add(current); historyIndex = 0; refillBag(false); }
    }

    private void refillBag(boolean includeCurrent) {
        bag.clear();
        for (String id : ordered) if (includeCurrent || !id.equals(current)) bag.add(id);
        Collections.shuffle(bag, random);
        if (includeCurrent && bag.size() > 1 && bag.get(0).equals(current)) Collections.swap(bag, 0, 1 + random.nextInt(bag.size() - 1));
    }
}
