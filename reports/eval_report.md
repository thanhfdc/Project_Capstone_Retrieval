# Quality and latency report

Generated 2026-10-20 08:57 UTC against `http://api:8000`. Serving images: **90327**, online encoder `siglip-onnx:siglip2`.

Latency = client-side time from sending the request to receiving the full JSON, result cache off, one request at a time, top_k=10.

| Type | Cases | Status acc. | Type detected | Precision@k | Intent coverage | p50 ms | p95 ms | p99 ms | max ms | ≥3 s | Errors | LLM calls | Tokens |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| multi_hop | 605 | 98% | 98% | 97% | 97% | 2.8 | 4.0 | 5.4 | 52.5 | 0 | 0 | 0 | 0 |
| multi_intent | 842 | 99% | 98% | 96% | 97% | 2.9 | 5.6 | 46.2 | 123.9 | 0 | 0 | 0 | 0 |
| robustness | 222 | 96% |  |  |  | 10.9 | 60.7 | 84.0 | 168.2 | 0 | 0 | 0 | 0 |
| single | 1507 | 99% | 100% | 95% | 96% | 3.0 | 40.5 | 55.0 | 95.3 | 0 | 0 | 0 | 0 |

## By variant

| Type | Variant | Cases | Status acc. | Precision@k |
|---|---|---:|---:|---:|
| multi_hop | 1_hop/founded | 19 | 100% | 100% |
| multi_hop | 1_hop/member_of | 10 | 100% | 100% |
| multi_hop | 1_hop/parent_of | 39 | 100% | 100% |
| multi_hop | 1_hop/parent_of_no_gender | 33 | 100% | 100% |
| multi_hop | 1_hop/sibling_of | 53 | 98% | 100% |
| multi_hop | 1_hop/sibling_of_no_gender | 48 | 98% | 82% |
| multi_hop | 1_hop/spouse_of | 59 | 98% | 100% |
| multi_hop | 1_hop/spouse_of_no_gender | 59 | 100% | 100% |
| multi_hop | 2_hop | 91 | 96% | 96% |
| multi_hop | negative | 192 | 99% |  |
| multi_intent | comma | 250 | 100% | 97% |
| multi_intent | same_photo | 91 | 89% | 82% |
| multi_intent | two_groups | 250 | 100% | 98% |
| multi_intent | union | 250 | 100% | 98% |
| robustness | gibberish | 25 | 100% |  |
| robustness | not_in_data | 30 | 97% |  |
| robustness | partial_name | 14 | 93% |  |
| robustness | photo_word_only | 3 | 100% |  |
| robustness | reordered_name | 75 | 91% |  |
| robustness | unknown_relation | 75 | 99% |  |
| single | case_space_punct | 250 | 100% | 98% |
| single | name | 250 | 100% | 97% |
| single | name+scene | 250 | 99% | 96% |
| single | no_diacritics | 250 | 100% | 97% |
| single | title | 250 | 100% | 96% |
| single | typo | 250 | 94% | 84% |

## Failed or suspicious cases

- `si_0025` [single/name] “ảnh Văn Khê” → no_seed_entity, precision 0.0; top: ảnh văn khê: no_seed_entity
- `si_0070` [single/name+scene] “Bear tại sự kiện” → ok, precision 0.0; top: bear: Đào Hà (người mẫu) | Long Vũ | Long Vũ
- `si_0081` [single/typo] “Trn Thị Thùy Dung Hoa hậu Việt Nam 2008” → no_seed_entity, precision 0.0; top: trn thị thùy dung hoa hậu việt nam 2008: no_seed_entity
- `si_0108` [single/case_space_punct] “  NGUYỄN VĂN HƯNG  !!” → ok, precision 0.2; top: nguyễn văn hưng: Nguyễn Văn Hưng, Nguyễn Văn Hùng (silat) | Nguyễn Văn Hùng (VHTTDL) | Nguyễn Văn Hưng
- `si_0141` [single/typo] “Tai Tzuying” → ok, precision 0.0; top: tai tzuying: Tho Nguyen
- `si_0147` [single/typo] “Đặng Hong Minh” → ok, precision 0.0; top: đặng hong minh: Hồng Minh, Hồng Minh (Giọng Hát Việt Nhí) | Hồng Minh, Hồng Minh (Giọng hát Việt nhí 2015) | Hồng Minh, Hồng Minh (Giọng hát Việt nhí 2015)
- `si_0161` [single/title] “MC Trang” → ok, precision 0.0; top: mc trang: Đức Bảo | Tự Long (Anh trai vượt ngàn chông gai) | Tự Long (Anh trai vượt ngàn chông gai)
- `si_0177` [single/typo] “TThug” → no_results, precision 0.0; top: tthug: no_results
- `si_0201` [single/typo] “Vũ Lân” → ok, precision 0.0; top: vũ lân: Vũ Lập | Vũ Lập | Vũ Lập
- `si_0219` [single/typo] “Huỳnh Nuyễn Mai Phương Hoa hậu Thế giới Việt Nam 2022” → no_seed_entity, precision 0.0; top: huỳnh nuyễn mai phương hoa hậu thế giới việt nam 2022: no_seed_entity
- `si_0239` [single/title] “ca sĩ Kuga” → ok, precision 0.0; top: ca sĩ kuga: Anh Khang (ca sĩ) | Ca sĩ Tuấn Hưng | Anh Tuấn (nhóm MTV)
- `si_0280` [single/name+scene] “Mademoiselle chụp ngoài trời” → ok, precision 0.0; top: mademoiselle chụp ngoài trời: Nguyễn Thị Ngọc Khánh (HHVN 1995) | Khanh Linh (the Yellow) | Hương Giang đại sứ LGBT Hanoi Pride
- `si_0289` [single/name] “ảnh Phạm Văn Dòng” → ok, precision 0.333; top: phạm văn dòng: Phạm Văn Đồng | Phạm Văn Đồng | Phạm Văn Đồng
- `si_0297` [single/typo] “Nguyn Duy Vĩ Sky Mavis” → no_seed_entity, precision 0.0; top: nguyn duy vĩ sky mavis: no_seed_entity
- `si_0359` [single/title] “nghệ sĩ Lê Thúy” → ok, precision 0.2; top: nghệ sĩ lê thúy: Lệ Thủy | Lê Thúy | Lệ Thủy
- `si_0362` [single/no_diacritics] “nguyen van toan” → ok, precision 0.4; top: nguyen van toan: Nguyễn Văn Toản | Nguyễn Văn Toản | Nguyễn Văn Toàn
- `si_0381` [single/typo] “Rbber” → no_results, precision 0.0; top: rbber: no_results
- `si_0399` [single/typo] “Trần Tuấn Dưng” → ok, precision 0.0; top: trần tuấn dưng: Trần Tuấn Hùng (guitar Bức Tường) | Trần Tuấn Hùng (guitar Bức Tường) | Trần Tuấn Hùng
- `si_0429` [single/typo] “Bên đạo Hà Lê” → ok, precision 0.0; top: bên đạo hà lê: Hà Lê | Hà Lê (rapper/đường phố) | Hà Lê (Anh trai vượt ngàn chông gai)
- `si_0430` [single/name+scene] “Quốc Khanh đang biểu diễn” → ok, precision 0.2; top: quốc khanh đang biểu diễn: Quốc Khánh (BTV thể thao VTV) | Quốc Khánh | Quốc Khánh (BTV thể thao VTV)
- `si_0433` [single/name] “ảnh Nguyễn Huệ” → ok, precision 0.0; top: nguyễn huệ: Quang Trung (diễn viên/KOL) | Quang Trung | Quang Trung (diễn viên/KOL)
- `si_0449` [single/title] “nghệ sĩ Nguyễn Thành Long” → ok, precision 0.0; top: nghệ sĩ nguyễn thành long: Nguyễn Thanh Long (GS), Nguyễn Thanh Long | Nguyễn Thanh Long (GS) | Nguyễn Thanh Long
- `si_0506` [single/no_diacritics] “phuong mai” → ok, precision 0.0; top: phuong mai: Phương Mai (người mẫu), Phương Mai người mẫu MC, MC Phương Mai (giữ) | Phương Mai (người mẫu), Phương Mai người mẫu MC, MC Phương Mai (giữ) | Phương Mai (người mẫu)
- `si_0539` [single/title] “ca sĩ GMC” → ok, precision 0.0; top: ca sĩ gmc: Phạm Hồng Phước | Hồng Phước (Idol) | Phạm Hồng Phước (ca sĩ)
- `si_0573` [single/typo] “Lna” → no_results, precision 0.0; top: lna: no_results
- `si_0591` [single/typo] “Gào” → ok, precision 0.0; top: gào: Hồ Quang Cua (gạo ST25) | Anh Hoàng Tuấn Anh sáng lập ATM gạo Sài Gòn 2020 COVID-19 | Hồ Quang Cua (gạo ST25)
- `si_0603` [single/typo] “Anh hng Võ Thị Sáu” → no_seed_entity, precision 0.0; top: hng võ thị sáu: no_seed_entity
- `si_0609` [single/typo] “stramer Độ Mixi fan tổ chức” → ok, precision 0.0; top: stramer độ mixi fan tổ chức: Độ Mixi | Độ Mixi | Độ Mixi
- `si_0628` [single/name+scene] “Buratinox tại sự kiện” → ok, precision 0.1; top: buratinox: Buratinox (ban nhạc rock) | Negav (Anh trai say hi) | Nguyễn Hoà Bình (Shark Bình) - NextTech
- `si_0657` [single/typo] “Rndy” → no_results, precision 0.0; top: rndy: no_results
- `si_0669` [single/typo] “Nhạc trưởg Nguyễn Khắc Thành” → ok, precision 0.0; top: nhạc trưởg nguyễn khắc thành: Nguyễn Khắc Thành (FPT/ĐH FPT) | Nguyễn Khắc Thành (FPT/ĐH FPT) | Nguyễn Khắc Thành (FPT/ĐH FPT)
- `si_0681` [single/typo] “Kimmse” → no_results, precision 0.0; top: kimmse: no_results
- `si_0682` [single/name+scene] “DSK trên sân khấu” → ok, precision 0.0; top: dsk trên sân khấu: Ca sĩ Đan Trường | NSND Thúy Ngần | Ngô Phương Lan (HHTGNV 2007)
- `si_0764` [single/no_diacritics] “nguyen thi huong” → ok, precision 0.0; top: nguyen thi huong: Nguyễn Thị Hương | Nguyễn Thị Hương | Nguyễn Thị Hương
- `si_0766` [single/name+scene] “Bùi Văn Quang đang biểu diễn” → no_seed_entity, precision 0.0; top: bùi văn quang đang biểu diễn: no_seed_entity
- `si_0771` [single/typo] “Tịnh Xuân Đức” → ok, precision 0.0; top: tịnh xuân đức: Xuân Đức | Xuân Đức | Xuân Đức
- `si_0777` [single/typo] “Tanh Hằng siêu mẫu Việt Nam” → no_seed_entity, precision 0.0; top: tanh hằng siêu mẫu việt nam: no_seed_entity
- `si_0791` [single/title] “ca sĩ Shark Hưng, Shark Bình, Shark Tank VN” → partial, precision 0.0; top: ca sĩ shark hưng: Shark Hưng (Phạm Thanh Hưng) | Shark Hưng (Phạm Thanh Hưng) | Shark Hưng (Phạm Thanh Hưng) / shark bình: Shark Bình (Nguyễn Hòa Bình), Shark Bình - Nguyễn Hòa Bình (NextTech) | Shark
- `si_0832` [single/name+scene] “Nguyễn Hữu Phước Nguyên tại sự kiện” → no_seed_entity, precision 0.0; top: nguyễn hữu phước nguyên: no_seed_entity
- `si_0861` [single/typo] “Trần Thàh” → ok, precision 0.0; top: trần thàh: MC Trấn Thành | MC Trấn Thành | MC Trấn Thành
- `si_0863` [single/title] “MC Trương Gia Bình” → ok, precision 0.4; top: mc trương gia bình: Headshot doanh nhân Trương Gia Bình FPT | Chân dung doanh nhân Trương Gia Bình (FPT) | Trương Gia Bình
- `si_0884` [single/no_diacritics] “son” → ok, precision 0.0; top: son: Sơn Ca | Thế Sơn | Nguyễn Thị Sơn (Sơn Kim Group)
- `si_0885` [single/typo] “Sam” → ok, precision 0.0; top: sam: MC Lại Văn Sâm | MC Lại Văn Sâm | MC Lại Văn Sâm
- `si_0921` [single/typo] “Nguyn Huy Dũng” → ok, precision 0.0; top: nguyn huy dũng: Nguyễn Huy Dung | Nguyễn Huy Dung | Nguyễn Huy Dung
- `si_0927` [single/typo] “Trần Văn Hưng” → ok, precision 0.0; top: trần văn hưng: Trần Văn Hùng | Trần Văn Hùng
- `si_0972` [single/case_space_punct] “  TOULIVER PRODUCER  !!” → ok, precision 0.1; top: touliver producer: Touliver | Touliver | Touliver (nhạc sĩ/producer)
- `si_0984` [single/case_space_punct] “  BẦU HIỂN  !!” → ok, precision 0.0; top: bầu hiển: Đỗ Quang Hiển | Đỗ Quang Hiển | Đỗ Quang Hiển
- `si_1019` [single/title] “MC Trần Tùng” → ok, precision 0.4; top: mc trần tùng: Trần Tung (Tuệ Trung Thượng Sĩ) | Trần Tùng (keyboard Bức Tường) | Trần Tùng (keyboard Bức Tường)
- `si_1023` [single/typo] “Đội tuyn bóng đá nữ Việt Nam vô địch SEA Games 32” → ok, precision 0.0; top: đội tuyn bóng đá nữ việt nam vô địch sea games 32: Vô địch WBO mini flyweight thế giới Nguyễn Thị Thu Nhi 2021, Nguyễn Thị Thu Nhi | Vô địch WBO mini flyweight thế giới Nguyễn Thị Thu Nhi 2021 | Vô đị
- `si_1029` [single/typo] “Ngyễn Văn Thanh” → ok, precision 0.4; top: ngyễn văn thanh: Nguyễn Văn Thành | Nguyễn Văn Thanh | Nguyễn Văn Thành
- `si_1031` [single/title] “MC Anna” → ok, precision 0.0; top: mc anna: RichChoi | Lăng LD | Phúc Bồ
- `si_1059` [single/typo] “Nhạc tính phòng Việt Nam” → ok, precision 0.0; top: nhạc tính phòng việt nam: Bùi Đình Thảo (nhạc sĩ, Đi học) | Cung văn (hát chầu văn cho hầu đồng) | Tô Lan Phương
- `si_1101` [single/typo] “Nuyễn Thị Loan Hoa khôi Thể thao” → no_seed_entity, precision 0.0; top: nuyễn thị loan hoa khôi thể thao: no_seed_entity
- `si_1119` [single/typo] “Blaka” → no_results, precision 0.0; top: blaka: no_results
- `si_1152` [single/case_space_punct] “  NGUYỄN QUANG HẢI  !!” → ok, precision 0.4; top: nguyễn quang hải: Nguyễn Quang Hải | Quang Hải | Nguyễn Quang Hải
- `si_1167` [single/typo] “Lê Ngyễn Bảo Ngọc Hoa hậu Liên lục địa Việt Nam 2022” → no_seed_entity, precision 0.0; top: lê ngyễn bảo ngọc hoa hậu liên lục địa việt nam 2022: no_seed_entity
- `si_1173` [single/typo] “Trần Anh Vơng” → ok, precision 0.0; top: trần anh vơng: Trần Anh Tông | Trần Anh Tông
- `si_1209` [single/typo] “Nhà son nhạc Vũ Nhật Tân” → ok, precision 0.0; top: nhà son nhạc vũ nhật tân: Vũ Nhật Tân | Vũ Nhật Tân | Vũ Nhật Tân
- `si_1213` [single/name] “ảnh Thanh Thủy” → ok, precision 0.0; top: thanh thủy: Thanh Thúy (hải ngoại), Thanh Thúy (ca sĩ, sinh 1943) | Thanh Thúy | Thanh Thúy (hải ngoại)
- `si_1221` [single/typo] “Hồ Văn Mời” → ok, precision 0.0; top: hồ văn mời: Hồ Văn Lợi | Hồ Văn Lợi | Hồ Văn Lợi
- `mu_2255` [multi_intent/same_photo] “Nguyễn Thời Trung chụp cùng Nguyễn Viết Trung” → no_results, precision 0.0; top: nguyễn thời trung chụp cùng nguyễn viết trung: no_results
- `mu_2256` [multi_intent/same_photo] “Hoàng Phạm chụp cùng Chillies” → ok, precision 0.125; top: hoàng phạm chụp cùng chillies: Hoàng Phạm (Chillies - vocal) | Hoàng Phạm (Chillies - vocal) | Hoàng Phạm (Chillies - vocal)
- `mu_2261` [multi_intent/same_photo] “Ảnh Thùy Tiên đăng quang Miss Grand 2021 chụp cùng Nguyễn Thúc Thùy Tiên” → no_seed_entity, precision 0.0; top: thùy tiên đăng quang miss grand 2021 chụp cùng nguyễn thúc thùy tiên: no_seed_entity
- `mu_2264` [multi_intent/same_photo] “Lil Knight chụp cùng LK” → ok, precision 0.333; top: lil knight chụp cùng lk: LK (Việt kiều rapper), Lil Knight (LK), LK (rapper) | Lil Knight (LK) | Lil Knight (LK), LK (rapper)
- `mu_2270` [multi_intent/same_photo] “Johnathan Hạnh Nguyễn chụp cùng Tăng Thanh Hà” → no_results, precision 0.0; top: johnathan hạnh nguyễn chụp cùng tăng thanh hà: no_results
- `mu_2275` [multi_intent/same_photo] “365 chụp cùng 365daband” → ok, precision 0.0; top: 365 chụp cùng 365daband: Nhóm 365daband, 365 (V.Music) | Nhóm 365daband | Nhóm 365daband
- `mu_2276` [multi_intent/same_photo] “Nguyễn Tiến Long chụp cùng Nguyễn Tiến Thanh” → needs_clarification, precision 0.0; top: 
- `mu_2277` [multi_intent/same_photo] “Lệ Thủy chụp cùng Lệ Thu” → needs_clarification, precision 0.0; top: 
- `mu_2280` [multi_intent/same_photo] “Mạnh Tuấn chụp cùng Minh Thu” → needs_clarification, precision 0.0; top: 
- `mu_2291` [multi_intent/same_photo] “Nguyễn Văn Chiến chụp cùng Nguyễn Nhân Chiến” → needs_clarification, precision 0.0; top: 
- `mu_2302` [multi_intent/same_photo] “Ảnh H'Hen Niê đăng quang HHHVN 2017 vương miện chụp cùng Ảnh H'Hen Niê đăng quang HHHV 2017” → no_results, precision 0.0; top: h hen niê đăng quang hhhvn 2017 vương miện chụp cùng ảnh h hen niê đăng quang hhhv 2017: no_results
- `mu_2303` [multi_intent/same_photo] “LK chụp cùng Lil Knight” → ok, precision 0.333; top: lk chụp cùng lil knight: LK (Việt kiều rapper), Lil Knight (LK), LK (rapper) | Lil Knight (LK) | Lil Knight (LK), LK (rapper)
- `mu_2310` [multi_intent/same_photo] “Đoàn Nguyên Đức Hoàng Anh Gia Lai rút ra điều hành chụp cùng Bầu” → ok, precision 0.2; top: đoàn nguyên đức hoàng anh gia lai rút ra điều hành chụp cùng bầu: Doanh nhân Đoàn Nguyên Đức Hoàng Anh Gia Lai rút ra điều hành, Ông Bầu (Đoàn Nguyên Đức - bóng đá) | Doanh nhân Đoàn Nguyên Đức Hoàng 
- `mu_2311` [multi_intent/same_photo] “Andrea chụp cùng An Tây” → ok, precision 0.1; top: andrea chụp cùng an tây: Andrea (Andrea Aybar), An Tây | An Tây | An Tây
- `mu_2326` [multi_intent/same_photo] “Nguyễn Thị Phương Thảo chụp cùng HDBank” → ok, precision 0.1; top: nguyễn thị phương thảo chụp cùng hdbank: Headshot doanh nhân Nguyễn Thị Phương Thảo, HDBank - Phó Chủ tịch là Phương Thảo | Headshot doanh nhân Nguyễn Thị Phương Thảo | Nguyễn Thị Phương Thảo
- `mu_2327` [multi_intent/same_photo] “Nguyễn Huệ chụp cùng Quang Trung” → ok, precision 0.0; top: nguyễn huệ chụp cùng quang trung: Quang Trung (diễn viên/KOL) | Quang Trung | Quang Trung (diễn viên/KOL)
- `mu_2328` [multi_intent/same_photo] “Ảnh Thùy Tiên đăng quang Miss Grand 2021 chụp cùng Thùy Tiên khóc khi đăng quang” → no_seed_entity, precision 0.0; top: thùy tiên đăng quang miss grand 2021 chụp cùng thùy tiên khóc khi đăng quang: no_seed_entity
- `mu_2333` [multi_intent/same_photo] “Lê Giang chụp cùng Lư Nhất Vũ” → needs_clarification, precision 0.0; top: 
- `ro_2411` [robustness/unknown_relation] “ông nội của Bear” → no_seed_entity, precision -; top: ông nội của bear: no_seed_entity
- `ro_2438` [robustness/not_in_data] “ảnh Thành Long” → ok, precision -; top: ảnh thành long: Lê Thành Long | Lê Thành Long | Lê Thành Long
- `ro_2453` [robustness/reordered_name] “lần nhiều máu hiến sĩ ca Sơn Ngọc” → ok, precision -; top: lần nhiều máu hiến sĩ ca sơn ngọc: Song Ngọc, Song Ngọc (nhạc sĩ) | Song Ngọc | Song Ngọc
- `ro_2454` [robustness/reordered_name] “Chung Thành Nguyễn” → ok, precision -; top: chung thành nguyễn: Thanh Nguyên | Thanh Nguyên | Thanh Nguyên
- `ro_2470` [robustness/reordered_name] “Nhân Trọng Phạm” → ok, precision -; top: nhân trọng phạm: Trang Phạm (người mẫu) | Trang Phạm (người mẫu) | Trang Phạm (người mẫu)
- `ro_2486` [robustness/reordered_name] “nữ tuyển đội Dung Tuyết thủ Cầu” → ok, precision -; top: nữ tuyển đội dung tuyết thủ cầu: Đào Thị Kiều Oanh | Phạm Hải Yến | Trần Thị Thùy Trang (Thiên An)
- `ro_2488` [robustness/reordered_name] “DX Huy DJ” → ok, precision -; top: dx huy dj: Nhạc sĩ Huy Du (giữ) | Nhạc sĩ Huy Du (giữ), Huy Du | Nhạc sĩ Huy Du (giữ)
- `ro_2490` [robustness/reordered_name] “Nguyên Văn Bùi” → ok, precision -; top: nguyên văn bùi: Nghệ nhân Nguyễn Văn Mùi (ca trù Thái Hà) | Nghệ nhân Nguyễn Văn Mùi (ca trù Thái Hà)
- `ro_2491` [robustness/reordered_name] “Châu Viễn giả Soạn” → ok, precision -; top: châu viễn giả soạn: Trần Đăng | Nguyễn Xuân Khánh | Viễn Châu
- `ro_2527` [robustness/partial_name] “Lê Thanh Thanh” → ok, precision -; top: lê thanh thanh: Lê Thanh Thản - Chủ tịch Mường Thanh | Lê Thanh Thản - Chủ tịch Mường Thanh | Lê Thanh Thản - Chủ tịch Mường Thanh
- `mu_2653` [multi_hop/1_hop/sibling_of_no_gender/no_cua] “em ca sĩ Duy Quang” → ok, precision 0.0; top: em ca sĩ duy quang: Duy Quang | Duy Quang | Duy Quang
- `mu_2660` [multi_hop/1_hop/sibling_of_no_gender/no_cua] “anh chị em Trịnh Vĩnh Trinh” → ok, precision 0.0; top: anh chị em trịnh vĩnh trinh: Trịnh Vĩnh Trinh | Trịnh Vĩnh Trinh | Trịnh Vĩnh Trinh
- `mu_2662` [multi_hop/1_hop/sibling_of_no_gender/no_cua] “em vua Thái Đức” → ok, precision 0.0; top: em vua thái đức: Nguyễn Nhạc | Nguyễn Nhạc | Nguyễn Nhạc
- `mu_2684` [multi_hop/1_hop/sibling_of_no_gender/no_cua] “anh chị em Phạm Nhật Vượng” → ok, precision 0.0; top: anh chị em phạm nhật vượng: Chân dung studio Phạm Nhật Vượng Forbes | Chân dung studio Phạm Nhật Vượng Forbes | Chân dung studio Phạm Nhật Vượng Forbes
- `mu_2716` [multi_hop/1_hop/sibling_of_no_gender/no_cua] “anh chị em Đinh Đức Thiện” → ok, precision 0.0; top: anh chị em đinh đức thiện: Đinh Đức Thiện | Đinh Đức Thiện | Đinh Đức Thiện
- `mu_2726` [multi_hop/1_hop/sibling_of_no_gender/photo_prefix] “ảnh anh chị em ruột của bà Trưng Nhị” → ok, precision -; top: anh chị em của Trưng Nhị: Trưng Trắc: Trưng Trắc
- `mu_2727` [multi_hop/1_hop/sibling_of/no_cua] “em gái bà Trưng Nhị” → ok, precision -; top: em gái của Trưng Nhị: Trưng Trắc: Trưng Trắc
- `mu_2731` [multi_hop/1_hop/sibling_of_no_gender/no_cua] “em ông Phạm Nhật Vũ” → ok, precision 0.0; top: em ông phạm nhật vũ: Phạm Nhật Vũ | Phạm Nhật Vũ | Phạm Nhật Vũ
- `mu_2743` [multi_hop/1_hop/sibling_of_no_gender/no_cua] “em Đặng Thị Hoàng Yến” → ok, precision 0.0; top: em đặng thị hoàng yến: Đặng Thị Hoàng Yến (Tân Tạo) | Đặng Thị Hoàng Yến (Tân Tạo) | Đặng Thị Hoàng Yến (Tân Tạo)
- `mu_2774` [multi_hop/1_hop/sibling_of_no_gender/no_cua] “em bà Trưng Trắc” → ok, precision 0.0; top: em bà trưng trắc: Trưng Trắc
- `mu_2824` [multi_hop/1_hop/spouse_of/no_cua] “vợ Trần Đình Long” → no_results, precision -; top: vợ trần đình long: no_results
- `mu_2911` [multi_hop/2_hop/sibling_of>parent_of/no_cua] “bố anh trai Đỗ Quang Vinh” → needs_clarification, precision 0.0; top: 
- `mu_2949` [multi_hop/2_hop/sibling_of>parent_of/no_cua] “bố anh trai ca sĩ Thái Hiền” → needs_clarification, precision 0.0; top: 
- `mu_2953` [multi_hop/2_hop/sibling_of>parent_of/no_cua] “bố anh trai Đỗ Vinh Quang” → needs_clarification, precision 0.0; top: 
- `mu_2958` [multi_hop/2_hop/sibling_of>parent_of/no_cua] “bố anh trai ca sĩ Thái Thảo” → needs_clarification, precision 0.0; top: 
- `mu_3039` [multi_hop/negative/missing_relation] “con trai của Bear” → no_seed_entity, precision -; top: con trai của bear: no_seed_entity
- `mu_3129` [multi_hop/negative/missing_relation] “con trai của Trang” → no_seed_entity, precision -; top: con trai của trang: no_seed_entity

## Manual cases (judge by eye)

- “bãi biển Nha Trang” → ok (44.3 ms): bãi biển nha trang: Alexandre Yersin (vi khuẩn học, Nha Trang) | Dưa Leo (diễn giả) | Hồ Vĩnh Khoa
- “hồ bơi và công viên nước ở Phú Quốc” → ok (73.7 ms): hồ bơi: Gil Lê / công viên nước: Nguyễn Đức Thanh
- “ảnh con trai chủ tịch Phạm Nhật Vượng” → ok (6.2 ms): con trai của Phạm Nhật Vượng, Chân dung studio Phạm Nhật Vượng Forbes, Headshot doanh nhân Phạm Nhật Vượng, Chân dung doanh nhân Phạm Nhật Vượng (Forbes): Phạm Nhật Quân Anh: Phạm Nhật Quân Anh | Phạm Nhật Quân Anh | Phạm Nhật Quân Anh / con trai của Phạm Nhật Vượng, Chân dung studio Phạm Nhật Vượng
- “ca sĩ đang hát trên sân khấu” → ok (88.8 ms): ca sĩ đang hát trên sân khấu: Anh Khang (ca sĩ) | Ca sĩ Lê Anh Dũng | Dương Trần Nghĩa
- “người mặc áo dài” → ok (54.1 ms): người mặc áo dài: Hà Phương (siêu mẫu) | Hà Quỳnh Như | Nguyễn Thị Định (cổ)
- “con trai của người sáng lập Vingroup” → ok (5.4 ms): con trai của người sáng lập Vingroup: Phạm Nhật Quân Anh: Phạm Nhật Quân Anh | Phạm Nhật Quân Anh | Phạm Nhật Quân Anh / con trai của người sáng lập Vingroup: Phạm Nhật Minh Hoàng: Phạm Nhật Minh Hoàng | Phạm Nhật Minh Hoàng | Phạm Nhật Minh Hoàng
- “cô dâu chú rể” → ok (48.2 ms): cô dâu chú rể: Cặp đôi cầu lông Nguyễn Tiến Minh - Vũ Thị Trang | Phạm Đức Huy | Lý Hải - Minh Hà (4 con)
- “cầu thủ bóng đá” → ok (68.4 ms): cầu thủ bóng đá: Hồ Minh Dĩ | Patrik Lê Giang | Lê Văn Hà
- “người đeo kính phát biểu” → ok (69.0 ms): người đeo kính phát biểu: Trần Quang Phương | Cao Toàn Mỹ | Vũ Thanh Mai
- “nguoi mac ao dai” → ok (55.1 ms): nguoi mac ao dai: Bích Trâm | Nguyễn Thị Định (cổ) | Ngọc Hân (người mẫu)
