# Series poster fonts (tools/series_poster.py)

All fonts are from the official Google Fonts repository (`github.com/google/fonts`, `ofl/<family>/`,
downloaded 2026-11-13) and licensed under the **SIL Open Font License 1.1**; each family's license
text is in `licenses/<Family>-OFL.txt`.  They are used only to set the series title on poster covers.

| file | family | style slot | changes |
|---|---|---|---|
| `MaShanZheng-Regular-GB2312L1.ttf` | Ma Shan Zheng | `brush` (historical / xianxia / palace) | subset |
| `ZCOOLXiaoWei-Regular-GB2312L1.ttf` | ZCOOL XiaoWei | `elegant` (romance / CEO / sweet; default) | subset |
| `ZCOOLQingKeHuangYou-Regular-GB2312L1.ttf` | ZCOOL QingKe HuangYou | `hard` (suspense / horror / revenge / sci-fi) | subset |
| `NotoSansSC-Bold-GB2312.ttf` | Noto Sans SC | `plain` (fallback bar, glyph-coverage fallback) | Bold instance + subset |
| `PlayfairDisplay-wght.ttf` | Playfair Display (variable) | English `elegant` | unmodified |
| `Cinzel-wght.ttf` | Cinzel (variable) | English `brush` (fantasy / historical / werewolf) | unmodified |
| `BebasNeue-Regular.ttf` | Bebas Neue | English `hard` | unmodified |

Subsetting (fontTools `subset`, layout features kept, hinting dropped) keeps the repository small:
the three display CJK fonts carry ASCII, GB2312 symbols and the 3,755 GB2312 level-1 hanzi
(about 3 MB instead of 4-8 MB each); Noto Sans SC carries all of GB2312 (6,763 hanzi).  A title
character a style font lacks is detected at render time and the next font in the chain is used
(style font -> Noto Sans SC -> the host CJK font from `nalu_media_tools.resolve_cjk_font`).

OFL notes: subsets/instances are Modified Versions.  None of the modified families declares a
Reserved Font Name that appears in its name (Noto Sans SC's RFN is "Source"), and the fonts are
never sold or distributed on their own.  Playfair Display (RFN "Playfair Display") is shipped
unmodified for that reason.
