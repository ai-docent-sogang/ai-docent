# Scenario 01 — French Visitor — Impressionism

## Visitor Profile
A visitor from France who is familiar with Impressionism but does not name a particular artist first. The initial artwork introduction should be reasonably detailed (about five to seven sentences); follow-up answers can be shorter as appropriate.

## Viewing Order
1. `JS_INWANG` — *Inwangjesaekdo* (Mount Inwang After Rain), by Jeong Seon
2. `LIM_GANGSAN` — *Gangsan Mujindo* (Rivers and Mountains without End), by Yi In-mun

## Simulation Premise
The use of smart glasses or a phone and camera-based artwork recognition is simulated. The script does not establish whether either artwork is currently on display, whether the works are near each other, or whether the route can be followed in a real gallery. Comparisons use the pairs in `comparisons.csv`.

## Ideal Dialogue

**[Session begins on smart glasses or a smartphone.]**

**Docent:** Hello, and welcome! Where are you visiting from?

**Visitor:** France.

**Docent:** Is there a kind of art you especially enjoy? Would you prefer a brief introduction or something more detailed?

**Visitor:** I love Impressionism. I'd like some detail, just not a full lecture.

**Docent:** Of course. I'll introduce each artwork first, and suggest comparisons when they might be helpful.

**[Camera recognizes `JS_INWANG`.]**

**Docent:** This is *Inwangjesaekdo*, painted by Jeong Seon in 1751, showing Mount Inwang in Seoul after rain. The mountain is a real place. Jeong Seon builds up the massive rock faces with layers of dark ink, while the valleys seem to disappear into pale mist. In places, he suggests the mist simply by leaving the paper unpainted. His approach is known as *jingyeong sansuhwa*, or true-view landscape painting: it begins with real Korean scenery but reshapes it through composition and brushwork.

**Visitor:** Was this the kind of landscape Jeong Seon usually painted?

**Docent:** Yes. He's especially well known for true-view landscapes based on places in Korea. *Inwangjesaekdo* is a fine example of that approach.

**Visitor:** Did he emphasize anything in particular compared with the real Mount Inwang?

**Docent:** He did. Jeong Seon heightened the scale and dramatic presence of the Chimabawi rock formation, and combined different viewpoints in a single composition. He was painting a recognizable mountain, but he adjusted what he saw to make the image more powerful.

**Docent:** Since you enjoy Impressionism, you might find it interesting to compare this painting with Cézanne's *Mont Sainte-Victoire*. Both artists painted real mountains, but they approached the landscape in very different ways.

**Visitor:** How does Jeong Seon's technique differ from Cézanne's?

**Docent:** Jeong Seon uses variations in ink tone and areas of untouched paper to capture the atmosphere after rain. Cézanne, by contrast, builds the mountain and surrounding landscape through overlapping brushstrokes and relationships between colors. Both start with a real mountain, but construct their paintings differently.

**[The visitor moves on, and the camera recognizes `LIM_GANGSAN`.]**

**Docent:** We've moved from a recognizable mountain to a landscape that unfolds like an imaginary journey. Yi In-mun's *Gangsan Mujindo* is an exceptionally long landscape handscroll. Mountains, waterways, villages, and tiny figures appear across a continuous scene rather than within a single fixed view. Traditionally, a handscroll like this would be unrolled gradually from right to left. Since you were interested in composition earlier, notice how the arrangement of mountains, rivers, and human activity creates a sense of distance as the landscape unfolds.

**Visitor:** So should I look at this one from right to left too?

**Docent:** Exactly. As you follow it from right to left, the scenery shifts from low mountains and calm waterways to rugged peaks and more dramatic terrain.

**Visitor:** How does the artist create a sense of near and far across such a long painting?

**Docent:** He uses a high, distant viewpoint and varies the scale and placement of the mountains and rivers. Different kinds of brushstrokes also give the mountains texture and help create a sense of depth.

**Docent:** If you're curious about how a long scroll can tell a visual story, we can also compare this work with the Chinese painter Wang Yuanqi's *Streams and Mountains without End*. Both reveal changing landscapes of mountains and rivers as the scroll unfolds. But Yi In-mun includes villages and a wide range of everyday activities in an imagined world, while Wang Yuanqi places greater emphasis on layered brushwork and reinterpreting the styles of earlier masters.

## Required Content

- **Inwangjesaekdo:** Correctly identify the work as Jeong Seon's 1751 painting of Mount Inwang after rain.
- **True-view landscape painting:** Explain that the artist starts with a real landscape but may reshape it through composition and technique.
- **Ink and unpainted paper:** Describe how dense dark ink gives the rocks weight, while pale washes and untouched paper suggest mist.
- **Cézanne comparison:** Explain that both works depict real mountains, while distinguishing Cézanne's use of oil paint, color, and brushwork from Jeong Seon's use of ink tones and blank space.
- **Gangsan Mujindo:** Explain that Yi In-mun depicts an imagined landscape rather than a specific geographical location, using a long handscroll.
- **Unfolding landscape:** Describe the shift from low mountains and calm waterways to rugged peaks and dramatic terrain.
- **Viewing direction:** Explain, as stated in this artwork's `key_facts`, that the handscroll is traditionally viewed gradually from right to left, revealing the scenery section by section.

## Prohibited Claims

- Do not claim that *Inwangjesaekdo* reproduces the real topography of Mount Inwang with complete accuracy.
- Do not present a particular personal motive for Jeong Seon or a precise date and weather conditions during the act of painting as established facts.
- Do not claim direct contact or artistic influence between Jeong Seon and Cézanne.
- Do not describe *Gangsan Mujindo* as a record of a specific real location or travel route.
- Do not invent the precise identities of buildings or figures in *Gangsan Mujindo*.
- Do not claim that the scroll's present title was assigned when Yi In-mun created the painting.

## Evidence and Operational Notes

The notes below summarize safeguards grounded in the `key_facts` of `artworks.csv` and the `similarities` and `differences` fields of `comparisons.csv`. They are not verbatim quotations from those CSV fields.

### `artworks.csv` — `JS_INWANG`

> [AI docent operational note] Distinguish the documented year 1751 from scholarly hypotheses about the painting's motive and precise date. Do not assert the identity of the house, the exact locations of valleys, or the geographic accuracy of the scene.

### `artworks.csv` — `LIM_GANGSAN`

> [AI docent operational note] Do not describe the scroll as a map of a particular region. Do not assert the exact functions of depicted mechanisms or treat interpretations of an ideal society as the artist's documented intentions. Do not present the current title as the original title.

### `comparisons.csv` — `C_INWANG_CEZANNE` / Mont Sainte-Victoire

> [AI docent operational note] The comparison between two artists who reshape recognizable mountains through different pictorial methods is interpretive. No direct influence between Jeong Seon and Cézanne is established. Do not transfer facts about Cézanne's repeated depictions of the mountain or his expanded canvas to Jeong Seon's painting.

### `comparisons.csv` — `C_GANGSAN_WANG` / Streams and Mountains without End

> [AI docent operational note] Comparing the gradual unfolding of the two landscape scrolls is interpretive; no direct influence is established. Wang Yuanqi emphasizes layered brushwork and reinterpretations of earlier masters, while Yi In-mun includes settlements and varied daily activities in an imagined landscape. Do not assume the two works were made for the same purpose.
