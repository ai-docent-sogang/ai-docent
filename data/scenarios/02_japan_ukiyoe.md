# Scenario — Japanese Visitor — Ukiyo-e

## Visitor Profile
A visitor from Japan who is generally familiar with ukiyo-e but does not mention a particular artist first. Initial artwork introductions should be 3–5 sentences long.

## Artwork Sequence
1. `JS_INWANG` — *Inwangjesaekdo (Mount Inwang After Rain)* by Jeong Seon
2. `KHD_SSIREUM` — *Ssireum (Korean Traditional Wrestling)*, from Kim Hong-do's *Album of Genre Paintings*

## Demonstration Assumptions
The glasses/smartphone interface and camera recognition are simulated. The scenario does not guarantee that the works are currently on display, located near one another, or accessible along a particular route. Comparisons use the pairs recorded in `comparisons.csv`.

## Ideal Dialogue

**[Session begins.]**

**Docent:** Welcome! Where are you visiting from?

**Visitor:** Japan.

**Docent:** What kinds of art are you familiar with? Would you prefer brief explanations or a little more detail?

**Visitor:** I like ukiyo-e. A few sentences at a time would be great.

**Docent:** Of course. I'll keep each explanation focused and concise.

**[Camera recognizes `JS_INWANG`.]**

**Docent:** This is *Inwangjesaekdo*, painted by Jeong Seon in 1751, showing Mount Inwang in Seoul after rainfall. Unlike the ukiyo-e woodblock prints you know, this is an original ink painting on paper. Jeong used dense, dark ink to give the rain-soaked rocks a sense of weight, while pale washes and untouched areas of paper suggest mist rising between the peaks. He started with a real Korean landscape but reshaped its composition for artistic effect—a hallmark of *jingyeong sansuhwa*, or true-view landscape painting.

**Visitor:** Can ink alone really create so many different effects?

**Docent:** Yes. By varying the amount of water and the way the brush is used, an artist can create a wide range of tones. Here, the contrast between the dark rocks and pale mist gives the landscape a sense of depth.

**Docent:** Since you enjoy ukiyo-e, you might find it interesting to compare this with Hokusai's *South Wind, Clear Sky*, often called *Red Fuji*. Both works feature a real mountain, but Hokusai uses bold red and blue areas in a multicolored woodblock print, while Jeong relies on ink and mist.

**Visitor:** Did Hokusai also change the way the real landscape looked rather than copying it exactly?

**Docent:** He did. Hokusai based his image on Mount Fuji but simplified its outline into a striking, recognizable shape. Where Jeong uses ink and mist to emphasize the mountain's grandeur, Hokusai creates a powerful impression through the contrast between the red mountain and blue sky.

**[The visitor moves on; the camera recognizes `KHD_SSIREUM`.]**

**Docent:** Kim Hong-do's *Ssireum* captures a traditional Korean wrestling match during the Joseon period. Two wrestlers grapple in the center, while the spectators' expressions and gestures bring the scene to life. Kim leaves most of the background empty, drawing our attention to the match. You can even spot a sweets vendor carrying a tray.

**Visitor:** What are the wrestlers holding on to?

**Docent:** They're gripping cloth belts called *satba*. The aim is to upset the other wrestler's balance and bring them to the ground.

**Visitor:** Was wrestling popular with people in the Joseon period, too?

**Docent:** Yes. People from different social backgrounds enjoyed ssireum during the Joseon period. Wrestling was also part of seasonal celebrations such as Dano, Baekjung, and Chuseok.

**Docent:** Since you like ukiyo-e, we could also compare this with a Hokusai woodblock print depicting two sumo wrestlers. It arranges the figures quite differently from Kim Hong-do's *Ssireum*.

**Visitor:** How is the arrangement different?

**Docent:** Kim shows the wrestlers surrounded by spectators watching the match. Hokusai's print, by contrast, uses a tall, narrow format to bring the two sumo wrestlers to the fore. Kim conveys the excitement of the whole gathering, while Hokusai directs our attention to the two figures themselves.

## Must Include / Required Response Content

- **Inwangjesaekdo:** Correctly identify the work as Jeong Seon's 1751 painting of Mount Inwang in Seoul after rain.
- **Ink technique:** Explain how dark ink conveys the weight and texture of rain-soaked rocks, while pale washes and unpainted paper evoke mist.
- **True-view landscape painting:** Explain that *jingyeong sansuhwa* begins with recognizable Korean scenery but may reshape it through composition and brushwork.
- **Comparison with Hokusai:** Distinguish Jeong Seon's ink painting from the multicolored woodblock print *Red Fuji*. Explain differences in mountain forms and in the use of color, ink tones, and contrast.
- **Ssireum:** Identify Kim Hong-do's work as a late-Joseon depiction of wrestling, with two central competitors and spectators showing varied reactions.
- **How ssireum works:** Explain that wrestlers grip *satba* belts and attempt to unbalance and bring down their opponents.
- **Comparison with sumo:** Explain that both works feature wrestlers, but Kim depicts a match surrounded by spectators, while Hokusai emphasizes two individually identified sumo wrestlers.

## Must Not Say / Prohibited Claims

- Do not describe *Inwangjesaekdo* as a geographically exact copy of Mount Inwang.
- Do not present theories about Jeong Seon's personal motivation or the exact completion date as established facts.
- Do not claim direct influence or contact between Jeong Seon and Hokusai.
- Do not claim that *Red Fuji* records the weather on a particular date.
- Do not declare a winner in *Ssireum*.
- Do not assign specific social identities to the depicted figures or identify the occasion as a particular holiday without evidence.
- Do not project modern ssireum rules directly onto the Joseon-period scene.
- Do not claim that ssireum and sumo have identical rules.
- Do not claim that Hokusai's sumo print documents a specific historical bout.

## Evidence and Operational Notes

The notes below summarize operational cautions grounded in `artworks.csv` and `comparisons.csv`. The dialogue and acceptance criteria above reflect the constraints for each artwork and comparison pair.

### `artworks.csv` — `JS_INWANG`

> [AI Docent Operational Note] Distinguish the documented year 1751 from scholarly interpretations of the artist's motivation and the exact date of completion. Do not assert the identity of the house, the precise location of valleys, or exact topographical fidelity.

### `artworks.csv` — `KHD_SSIREUM`

> [AI Docent Operational Note] Do not assert who wins, identify the social status of individual figures, or name a particular holiday. Do not apply modern competition rules uncritically to the Joseon-period scene.

### `comparisons.csv` — `C_INWANG_HOKUSAI` / South Wind, Clear Sky (Gaifū kaisei), also known as Red Fuji, from the series Thirty-six Views of Mount Fuji

> [AI Docent Operational Note] Comparisons of mountain shapes and the depiction of weather are interpretive; direct artistic influence has not been established. Do not treat Hokusai's red Mount Fuji as a record of conditions on a specific day. Do not mistake different impressions of the same print design for separate original works.

### `comparisons.csv` — `C_KHD_HOKUSAI_SUMO` / The Sumo Wrestlers Wadagahara Jinshirō and Kachōzan Gorokichi

> [AI Docent Operational Note] The comparison concerns figure depiction and composition in Korean ssireum and Japanese sumo, not documented direct influence. Hokusai's print, dated to around 1783, portrays two named sumo wrestlers. Do not claim the two sports have identical rules or that Kim Hong-do's *Ssireum* records a particular historical match.
