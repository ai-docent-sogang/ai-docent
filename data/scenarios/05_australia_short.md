# Scenario — Australian Visitor — Very Brief Responses

## Visitor Profile
From Australia, with no particular familiarity with art. Keep every response from the AI docent to one or two sentences.

## Viewing Order
1. `KHD_SSIREUM` — *Ssireum (Korean Wrestling)*, from the *Album of Genre Paintings by Danwon*
2. `SYB_BABY` — *Woman Carrying a Baby on Her Back*
3. `CHAEKGADO_6` — *Chaekgado*, Six-Panel Folding Screen

## Demonstration Assumptions
The smart glasses/smartphone and camera-based artwork recognition are simulated. The scenario does not guarantee that the works are currently on display, located near one another, or connected by an actual visitor route. Comparisons use the artwork pairings specified in `comparisons.csv`.

## Ideal Sample Dialogue

**[Session begins.]**

**Docent:** Hello! Which country are you visiting from?

**Visitor:** Australia.

**Docent:** Is there any kind of art you're particularly familiar with? Would you prefer brief explanations or more detail?

**Visitor:** Not really. I've only got five minutes, so please keep it very short.

**Docent:** Of course. I'll keep each explanation to a sentence or two.

**[Camera recognizes `KHD_SSIREUM`.]**

**Docent:** In Kim Hong-do's *Ssireum*, two wrestlers grapple while a crowd gathers around to watch. The nearly empty background draws your attention to the match.

**Visitor:** What's the person carrying a tray selling?

**Docent:** That's a vendor selling *yeot*, a traditional Korean sweet. Little details like this bring the gathering to life.

**Visitor:** How do you win at ssireum?

**Docent:** You win by making your opponent touch the ground with any part of their body other than their feet.

**Docent:** You can compare this with Bruegel's *The Peasant Wedding*. Both show lively gatherings, but one centres on a wrestling match and the other on a wedding feast.

**[Visitor moves on; camera recognizes `SYB_BABY`.]**

**Docent:** Shin Yun-bok's *Woman Carrying a Baby on Her Back* depicts a woman with a child on her back. Notice her elaborate hairstyle, short *jeogori* jacket, and full skirt, all features of women's fashion at the time.

**Visitor:** Is she the baby's mother?

**Docent:** The scene may evoke a mother's love, but we don't know for certain whether they're actually mother and child.

**Visitor:** Who wrote the words beside the painting?

**Docent:** The inscription was written by someone who used the name Buseol Geosa. Their true identity remains unknown.

**Docent:** Utamaro's *Mother and Child* also depicts a woman and a child. The museum describes the Japanese work as a mother-and-child scene, but the relationship between the figures in the Korean painting is unconfirmed.

**[Visitor moves on; camera recognizes `CHAEKGADO_6`.]**

**Docent:** This is a six-panel folding screen called *Chaekgado*, depicting bookshelves. Shading and perspective make the shelves appear three-dimensional.

**Visitor:** Why did the artist paint the cabinet doors as if they're slightly open?

**Docent:** Making the doors look partly open gives the shelves a greater sense of depth. This is called *trompe-l'œil*, or an optical illusion.

**Docent:** Somerby's *Trompe l'oeil Painting* also makes books on a shelf look real. Unlike the Korean six-panel screen, though, it depicts a single shelf scene.

**Visitor:** That's perfect. Thank you!

**Docent:** You're very welcome. Enjoy the rest of your visit!

## Required Points / Essential Response Content

- ** *Ssireum*:** Explain that this Joseon-period genre painting by Kim Hong-do depicts two wrestlers competing as spectators gather around to watch.
- **Details of the wrestling scene and how a match is won:** Explain that the wrestlers grapple while holding each other's *satba* (wrestling belts), that a *yeot* vendor carrying a tray appears among the spectators, and how a ssireum match is generally won. Do not assume that all details of modern competition rules applied to the Joseon-period scene.
- **Comparison with Bruegel:** Explain that Kim Hong-do's *Ssireum* and Bruegel's *The Peasant Wedding* both portray lively gatherings, but one shows a wrestling match while the other shows a wedding feast.
- ** *Woman Carrying a Baby on Her Back*:** Explain that this work by Shin Yun-bok depicts a woman carrying a child on her back, and point out period clothing and styling such as her short *jeogori*, full skirt, and elaborate hairstyle.
- **Relationship between the woman and child:** Explain that the painting may suggest maternal affection, but it has not been established that the two figures are actually mother and child.
- **Author of the inscription:** Explain that the writing on the painting is associated with the name Buseol Geosa, but the person's true identity has not been established.
- **Comparison with Utamaro:** Explain that both works depict a woman and child, but Utamaro's work is described as a mother-and-child scene, whereas the relationship between the figures in Shin Yun-bok's painting remains uncertain.
- ** *Chaekgado*:** Explain that this six-panel folding screen depicts books and various objects arranged on shelves, using shading and perspective to create the illusion of a real, three-dimensional bookcase.
- **Depiction of the cabinet doors:** Explain that the doors, painted to appear partly open, create a trompe-l'œil effect that emphasizes depth.
- **Comparison with Somerby:** Explain that both works make books and objects appear lifelike, but the Korean *Chaekgado* is a six-panel folding screen, while Somerby's painting depicts books and objects arranged on a single shelf.

## Prohibited Claims / What the Docent Must Not Say

- Do not claim without evidence who won the match in *Ssireum*, that it took place during a particular holiday, or that it depicts a specific historical match.
- Do not assume that modern ssireum competition rules applied unchanged to the Joseon-period match depicted in the painting.
- Do not present satire or a moral lesson in Bruegel's *The Peasant Wedding* as the artist's definitively established intention.
- Do not state as fact that the woman in *Woman Carrying a Baby on Her Back* is the child's biological mother.
- Do not infer that the woman was a *gisaeng* (Korean courtesan/entertainer), or assign her a specific social status, solely from her clothing and hairstyle.
- Do not present Buseol Geosa's true identity or relationship to Shin Yun-bok as established fact.
- Do not assume that the confirmed mother-and-child relationship in Utamaro's work also applies to Shin Yun-bok's painting.
- Do not describe the cabinet doors in *Chaekgado* as actual doors on a physical, three-dimensional structure.
- Do not present a specific personal reason for the artist's depiction of partly open doors as an intention confirmed by historical records.
- Do not claim that this six-panel screen was commissioned by a particular king or that its exact date of creation is known.
- Do not claim without evidence that the Korean *Chaekgado* and Somerby's painting directly influenced one another.

## Source Material and Operational Notes
The notes below are drawn from the operational notes in `artworks.csv` and `comparisons.csv`. The constraints for each artwork and comparison pair are reflected in the dialogue and acceptance criteria above.

### `artworks.csv` — `KHD_SSIREUM`
> [AI Docent Operational Note] Do not make definitive claims about the winner, the figures' social status, or a particular holiday. Do not apply modern competition rules unchanged to a Joseon-period scene.

### `artworks.csv` — `SYB_BABY`
> [AI Docent Operational Note] Do not make definitive claims about the woman's social status or her relationship to the child. Buseol Geosa's identity, the date the inscription was written, and the reading of the Waganun seal remain uncertain. Do not treat literary comparisons as evidence of direct influence.

### `artworks.csv` — `CHAEKGADO_6`
> [AI Docent Operational Note] Do not confuse this work with other *chaekgado* pieces in different collections. Do not make definitive claims about the identity of the yellow fruit, the date of creation, or direct copying from Chinese paintings.

### `comparisons.csv` — `C_KHD_BRUEGEL` / Peasant Wedding
> [AI Docent Operational Note] Comparisons of the crowd arrangements and depictions of everyday life in the two works are interpretive; no direct influence between them has been established. Do not assert that satire or a moral message was Bruegel's definitive artistic intention. Do not assign *Ssireum* to a specific holiday or claim to know the actual date of the match depicted.

### `comparisons.csv` — `C_BABY_UTAMARO` / Mother and Child
> [AI Docent Operational Note] Comparing the gestures of the women and children is interpretive; no direct influence between the works has been established. The actual family relationship between the woman and child in Shin Yun-bok's painting is unknown, whereas the museum describes Utamaro's work as a mother and child playing together. Do not definitively identify the woman in Shin Yun-bok's painting as a *gisaeng* or the child's biological mother.

### `comparisons.csv` — `C_CHAEK_SOMERBY` / Trompe l'oeil Painting
> [AI Docent Operational Note] Comparing the illusionistic depiction of books and objects is interpretive; no direct influence between the works has been established. Somerby's work was checked against its official collection record (Historic New England, GUSN 3094) and the artwork image on the official page provided. The image shows a single shelf holding books, papers or letters, a container resembling an inkwell, and shading and arrangements that create an impression of depth. Specific item descriptions and quantities, including pamphlets and two quill pens, come from the collection record and were not all independently identifiable in the supplied image. Do not apply symbolic interpretations of objects such as the watermelon in Joseon *chaekgado* directly to the American still life, or assert that both works depict actual bookcases serving the same purpose.
