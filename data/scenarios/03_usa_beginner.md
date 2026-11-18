# Scenario — American Visitor — New to Korean Art

## Visitor Profile
A visitor from the United States with no particular favorite artist or specialist knowledge of art. Use plain English and short to medium-length explanations.

## Artwork Sequence
1. `KHD_SEODANG` — *Seodang (A Village School)*, from Kim Hong-do's *Album of Genre Paintings*
2. `CHAEKGADO_6` — *Chaekgado (Bookshelf Painting)*, Six-Panel Folding Screen

## Demonstration Assumptions
The glasses/smartphone interface and camera recognition are simulated. The scenario does not guarantee that the artworks are currently on display, near each other, or accessible along a particular route. Comparisons use the pairs recorded in `comparisons.csv`.

## Ideal Dialogue

**[Session begins.]**

**Docent:** Hello! Where are you visiting from?

**Visitor:** The United States.

**Docent:** Are there any art styles you're familiar with? Would you prefer a brief explanation or something more detailed?

**Visitor:** Not really. Please keep it simple.

**Docent:** Of course. I'll explain any unfamiliar terms as we go.

**[Camera recognizes `KHD_SEODANG`.]**

**Docent:** This is *Seodang* by Kim Hong-do. It shows a scene in a traditional Korean village school during the Joseon period. One child is crying in front of the teacher, while the other students react in different ways. With just a few figures and an almost empty background, Kim brings an everyday moment to life.

**Visitor:** Why is the child crying?

**Docent:** The museum suggests that the child may have just been punished with a switch. But that's an interpretation of the painting, not a confirmed account of what happened.

**Visitor:** What did children learn in schools like this?

**Docent:** They read classical texts aloud, memorized passages, and learned what they meant. Teachers also checked their progress through recitation and questions.

**Visitor:** Do we know which text the crying child was memorizing?

**Docent:** We don't know which text the child was studying. Children in these schools learned classical writings, but the painting doesn't tell us exactly what this child was reading or reciting.

**Docent:** Another interesting comparison is Pieter Bruegel the Elder's *Children's Games*. It shows children playing all kinds of games in a European town square and its streets. Both artists capture children's varied actions and expressions, but Kim focuses on a single moment in a small classroom, while Bruegel fills a much larger space with many different games.

**Visitor:** What kinds of games are the children playing in Bruegel's painting?

**Docent:** They're rolling hoops, spinning tops, playing leapfrog, and playing blind man's buff, among many other games. Some children are even imitating things adults do.

**[The visitor moves on; the camera recognizes `CHAEKGADO_6`.]**

**Docent:** This is *Chaekgado*, a Korean six-panel folding screen showing bookshelves filled with objects. Alongside books and writing tools, you'll find treasured possessions. The artist uses perspective and shading to make the painted shelves look as if they have real depth. Take a closer look at the objects tucked among the books and the door that appears to be partly open.

**Visitor:** Books make sense on a shelf, but why is there a watermelon?

**Docent:** Chaekgado paintings often include valuable, decorative, and symbolic objects alongside books. Watermelons are sometimes interpreted as symbols of the wish for many descendants, but we don't know exactly why this particular artist included one.

**Visitor:** How did the artist make that painted door look like it could actually open?

**Docent:** By using perspective, outlines, and shading, the artist made the door look as though it's opening at an angle into the space. This kind of visual illusion is called *trompe-l'œil*, a French term meaning “deceive the eye.”

**Docent:** For another comparison, the American artist Frederic Thomas Somerby's *Trompe l'oeil Painting* shows books and writing materials on a single shelf. Both paintings make everyday objects look remarkably real, but the Korean work is a multi-panel folding screen, while the American work is a still life showing one shelf.

## Required Content / Key Answers

- **Seodang**: Explain that Kim Hong-do depicts a Joseon village-school scene with a crying child before the teacher and classmates showing a range of reactions.
- **Teaching in a seodang**: Explain that students read classical texts repeatedly, memorized them, learned their meanings, and were assessed through recitation and explanation.
- **Interpreting the crying child**: Explain that punishment with a switch or failure in a recitation assessment are interpretations based on historical practices and the image, not confirmed events.
- **Comparison with Bruegel**: Explain that both works depict children's actions and responses vividly, but Kim concentrates on one classroom episode while Bruegel depicts many games across a town square and streets.
- **Chaekgado**: Explain that this Joseon painting arranges books, writing implements, and treasured objects on shelves, including decorative and symbolic items alongside scholarly possessions.
- **Symbolism in chaekgado**: Explain that fruits with many seeds, such as watermelons, may symbolize hopes for numerous descendants within the broader chaekgeori tradition.
- **Illusionistic techniques**: Explain how perspective, shading, and partly open-looking cabinet doors make a flat painting resemble a three-dimensional bookshelf.
- **Comparison with Somerby**: Explain that both paintings make books and objects related to reading or scholarship look real, but the Korean work is a six-panel screen with many objects, while Somerby's American still life depicts books and writing materials on one shelf.

## Prohibited Claims / What Not to Say

- Do not state definitively why the child in *Seodang* is crying or what the child did wrong.
- Do not invent the title or contents of a text the child recited, or the exact punishment the teacher imposed.
- Do not present the teacher's feelings as objectively established facts.
- Do not describe Bruegel's *Children's Games* as a school lesson or a depiction of seodang education.
- Do not assert a particular moral lesson or educational intention as Bruegel's confirmed purpose.
- Do not claim direct artistic influence between Kim Hong-do and Bruegel.
- Do not present an exact date or artist for this *Chaekgado* as confirmed.
- Do not identify the yellow fruit in *Chaekgado* definitively as Buddha's hand citron.
- Do not treat the watermelon's symbolic meaning as the artist's proven personal intention.
- Do not claim this *Chaekgado* belonged to a particular king or was commissioned for the royal court.
- Do not transfer Korean chaekgado symbolism to Somerby's painting or claim a direct influence between the two works.

## Source References and Operational Notes
The following AI docent operational notes are quoted from `artworks.csv` and `comparisons.csv` in Korean. The constraints for each artwork and comparison are reflected in the dialogue and evaluation criteria above.

### `artworks.csv` — `KHD_SEODANG`

> [AI Docent Operational Note] Present corporal punishment with a switch and failure in a recitation assessment as possible interpretations, not established facts. Do not state a definitive reason for the child's crying. Do not attribute specific brushwork techniques to particular figures without sufficient evidence.

### `artworks.csv` — `CHAEKGADO_6`

> [AI Docent Operational Note] Do not confuse this work with other chaekgado paintings in museum collections. Do not make definitive claims about the identity of the yellow fruit, the date of creation, or direct imitation of Chinese paintings.

### `comparisons.csv` — `C_SEODANG_BRUEGEL` / Children's Games

> [AI Docent Operational Note] Comparing the children's social behavior across the two paintings is an interpretation; no direct influence between the artists has been established. Distinguish interpretations of corporal punishment or a failed recitation assessment in *Seodang* from confirmed facts. Do not describe *Children's Games* as a school lesson or assert a definitive moral intention on Bruegel's part.

### `comparisons.csv` — `C_CHAEK_SOMERBY` / Trompe l'oeil Painting

> [AI Docent Operational Note] Comparing the illusionistic depiction of books and objects in the two works is interpretive, and no direct influence between them has been established. The official collection record for Somerby's painting (Historic New England, GUSN 3094) was cross-checked against the image provided from the official collection page. The image supports the identification of a single shelf holding books, papers and letters, a container resembling an inkwell, and the use of shading and arrangement to create an illusion of depth. Details such as pamphlets and two quill pens come from the collection record and were not all independently identifiable in the supplied image. Do not transfer symbolic interpretations associated with Joseon chaekgado, such as the watermelon, directly to the American still life, or assume that both paintings depict actual bookshelves serving the same purpose.
