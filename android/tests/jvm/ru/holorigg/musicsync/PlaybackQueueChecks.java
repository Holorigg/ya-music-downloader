package ru.holorigg.musicsync;

import org.junit.Test;
import java.util.*;
import static org.junit.Assert.*;

/** Small deterministic checks for queue navigation independent of Android media setup. */
public class PlaybackQueueChecks {
    private static final List<String> IDS = Arrays.asList("a", "b", "c", "d");

    @Test public void orderedQueueStopsAtEndUnlessRepeatAllIsEnabled() {
        PlaybackQueue queue = new PlaybackQueue(new Random(7));
        queue.setQueue(IDS, "b");

        assertEquals("c", queue.next(false));
        queue.accepted("c");
        assertEquals("d", queue.next(false));
        queue.accepted("d");
        assertNull(queue.next(false));
        assertEquals("a", queue.next(true));
    }

    @Test public void shuffleVisitsEveryOtherTrackOnceAndSupportsHistory() {
        PlaybackQueue queue = new PlaybackQueue(new Random(31));
        queue.setQueue(IDS, "a");
        queue.setShuffle(true);

        List<String> traversal = new ArrayList<>();traversal.add("a");
        for (int i = 0; i < IDS.size() - 1; i++) {
            String next = queue.next(false);
            assertNotNull(next);
            assertFalse("shuffle must not repeat before the bag is exhausted", traversal.contains(next));
            traversal.add(next);
            queue.accepted(next);
        }
        assertEquals(IDS.size(), traversal.size());
        assertEquals(IDS.size(), new HashSet<>(traversal).size());
        assertNull(queue.next(false));

        assertNotNull(queue.previous(false));
        String forward = queue.next(false);
        assertEquals("moving forward after Previous returns to the same history entry", traversal.get(3), forward);
    }

    @Test public void repeatAllStartsANewShuffleCycleWithoutRepeatingCurrentImmediately() {
        PlaybackQueue queue = new PlaybackQueue(new Random(12));
        List<String> cycleIds=IDS.subList(0, 3);
        queue.setQueue(cycleIds, "a");
        queue.setShuffle(true);
        List<String> traversal=new ArrayList<>();traversal.add("a");
        for(int i=0;i<9;i++){String next=queue.next(true);assertNotNull(next);traversal.add(next);queue.accepted(next);}
        for(int start=0;start+cycleIds.size()<=traversal.size();start+=cycleIds.size()){
            Set<String> cycle=new HashSet<>(traversal.subList(start,start+cycleIds.size()));
            assertEquals("every complete shuffle pass visits each track once",cycleIds.size(),cycle.size());
        }
        for(int i=1;i<traversal.size();i++)assertNotEquals("shuffle should not immediately repeat a track",traversal.get(i-1),traversal.get(i));
    }

    @Test public void replacingQueueDeduplicatesIdsAndResetsNavigation() {
        PlaybackQueue queue = new PlaybackQueue(new Random(4));
        queue.setQueue(Arrays.asList("a", "a", "b", "", null, "c"), "b");

        assertEquals(Arrays.asList("a", "b", "c"), queue.ids());
        assertEquals("c", queue.next(false));
        queue.accepted("c");
        queue.setQueue(Arrays.asList("x", "y"), "x");
        assertEquals("y", queue.next(false));
        queue.accepted("y");
        assertNull(queue.next(false));
    }
}
