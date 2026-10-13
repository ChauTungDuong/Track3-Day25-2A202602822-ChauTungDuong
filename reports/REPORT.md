# Lab 25B — Report

**Họ tên / nhóm:** Châu Tùng Dương  **MSV:** 2A202602822  **Commit:** a3f9ce7078c14d183ed1e95d311a2df59bc86855  **Điểm tự động (`make grade`):** 84.0 / 88

> Mọi nhận định phải có số. Dán số từ `reports/gameday/*.json`, `reports/workflows.json`, `reports/slo.json`.

## 1. Kết quả Game Day (naive vs của bạn)

| Băng | Client | availability | p95 (s) | amplification | retry_ratio | cost/turn | recovery (s) | PASS? |
|---|---|---:|---:|---:|---:|---:|---:|:---:|
| G1 | naive | 0.7194 | 7.157 | 7.738 | 6.738 | 2.163 | 4.0 | FAIL |
| G1 | yours | 1.0000 | 4.776 | 1.062 | 0.002 | 2.101 | 0.0 | PASS |
| G2 | naive | 0.4560 | 15.034 | 9.904 | 8.904 | 4.627 | 155.0 | FAIL |
| G2 | yours | 1.0000 | 10.920 | 1.041 | 0.007 | 2.119 | 0.0 | PASS |
| G3 | naive | 1.0000 | 4.768 | 1.164 | 0.164 | 2.328 | 0.0 | FAIL |
| G3 | yours | 1.0000 | 4.660 | 1.060 | 0.034 | 2.145 | 0.0 | PASS |
| G4 | naive | 1.0000 | 13.764 | 1.004 | 0.004 | 2.008 | 0.0 | FAIL |
| G4 | yours | 1.0000 | 5.562 | 1.015 | 0.002 | 2.072 | 0.0 | PASS |
| G5 | naive | 0.3699 | 5.359 | 17.030 | 16.030 | 2.124 | None | FAIL |
| G5 | yours | 0.8179 | 5.477 | 1.003 | 0.002 | 2.504 | None | PASS |
| G6 | naive | 0.5170 | 4.836 | 12.344 | 11.344 | 2.009 | 0.0 | FAIL |
| G6 | yours | 1.0000 | 5.961 | 1.055 | 0.019 | 2.189 | 0.0 | PASS |

## 2. Cấu hình client và lý do

| Tham số | Giá trị | Vì sao (dựa trên băng nào, số liệu nào) |
|---|---:|---|
| attempt_timeout_s | 8.0 | Dựa trên G6: khi alpha sập và alpha-eu treo, timeout 8.0s giúp client kịp failover sang beta trong turn deadline 30s. Nếu để 30s như Thí nghiệm 2, 122 request bị chết do hết hạn deadline. |
| max_attempts_per_provider | 2 | Dựa trên G3: cho phép đúng 1 lần retry trên cùng provider khi gặp transient error (500), giúp retry_ratio đạt 0.034 <= 0.10 mà không dội tải bùng nổ như naive (16.4%). |
| backoff_base_s / cap_s | 0.25 / 4.0 | Dựa trên G1: phân tán tải bằng Full Jitter tránh thundering herd sau 429 rate limit spike; cap 4.0s đảm bảo retry vẫn kịp thời hạn xử lý của lượt. |
| retry_budget_ratio | 0.1 | Dựa trên G2 & G3: giới hạn lượng retry không vượt quá 10% request gốc. Ngay cả khi breaker bị hỏng (Thí nghiệm 1), budget giữ amplification ở 1.383 thay vì 1.672. |
| breaker.window_size / min_calls | 20 / 10 | Đủ mẫu thống kê (10 call) để không trip nhầm lúc nửa đêm ít request, nhưng đủ nhạy để trip trong vòng 10 call khi tỷ lệ lỗi tăng vọt ở G2 và G6. |
| breaker.failure_rate_threshold | 0.5 | Dựa trên G6: khi 50% call gặp lỗi quá tải/server/timeout, breaker lập tức OPEN để chuyển toàn bộ traffic sang deployment dự phòng tiếp theo. |
| breaker.slow_call_s | 5.0 | Dựa trên G4: bình thường alpha chạy ~1.2s; khi bị chậm thêm 5s (>6.2s), slow call detection trip breaker giúp p95 giảm từ 13.764s (naive) xuống 5.562s (yours). |
| breaker.open_duration_s | 10.0 | Khoảng thời gian cách ly để provider quá tải xả hàng đợi và phục hồi; phù hợp với chu kỳ phục hồi của provider. |
| breaker.half_open_max_probes | 2 | Giới hạn tối đa 2 request thăm dò khi HALF-OPEN, ngăn chặn thundering herd đè bẹp provider vừa mới hồi phục. |

Sơ đồ quyết định của `on_error`:

```
                    [on_error nhận lỗi từ Provider]
                                  │
                                  ▼
                   Phân loại lỗi qua classify(err)
                                  │
         ┌────────────────────────┼────────────────────────┐
         ▼                        ▼                        ▼
  [CLIENT_ERROR]           [RATE_LIMITED /          [OVERLOADED /
  (400, 401, 422)          QUOTA_EXHAUSTED]         SERVER_ERROR /
         │                        │                    TIMEOUT]
         ├─ breaker.release()     ├─ breaker.release()     │
         │                        │                        ├─ breaker.on_failure()
         └─ GiveUp("client_error")├─ Cooldown provider     │
            (không retry,            (retry_after/quota_s) └─ tries < max_attempts VÀ
             không failover)      │                           budget cho phép VÀ
                                  └─ Failover sang             còn đủ deadline?
                                     provider tiếp theo             │
                                     ngay lập tức           ┌───────┴───────┐
                                                            ▼               ▼
                                                          [CÓ]            [KHÔNG]
                                                            │               │
                                                     Retry cùng provider  Failover sang
                                                     với FullJitter delay provider tiếp theo
```

## 3. Ba thí nghiệm (mỗi cái 3–5 câu + số)

1. **Retry budget là lớp phòng thủ cuối.** Khi vô hiệu hóa breaker (`min_calls = 1000000000`) và tăng `max_attempts_per_provider: 5`, nếu vẫn giữ Retry Budget thì ở G2 amplification chỉ là 1.383, retry_ratio = 0.058 và recovery = 0.0s (availability 99.87%). Ngược lại, khi tắt Retry Budget, amplification trên G2 vọt lên 1.672, retry_ratio vọt lên 0.491 và recovery bị kéo dài lên 30.0s (availability tụt còn 96.49%). Ngay cả khi Circuit Breaker hoạt động đúng, Retry Budget vẫn tối quan trọng vì đây là chốt chặn tài nguyên toàn cục (global token bucket) ngăn chặn bão retry diện rộng trong trường hợp breaker bị cấu hình sai, chưa kịp phản ứng hoặc lỗi phân tán trên nhiều provider.
2. **`attempt_timeout_s: 30`.** Khi tăng timeout lên 30s, availability ở G6 tụt từ 100% xuống 94.88%, đồng thời sinh ra 122 lượt give up (`give_up_reasons: {'deadline': 109, 'no_provider_available': 13}`) vì client kiên nhẫn chờ provider A bị sập quá lâu dẫn đến hết sạch turn deadline 30s trước khi kịp failover sang beta. Đáng chú ý, latency p95 của G6 lại giảm từ 6.016s xuống 5.306s do hiện tượng *survivorship bias* (các lượt treo >8s bị rớt khỏi tập thành công nên p95 chỉ tính trên các lượt may mắn thành công sớm). Băng G4 gần như không đổi (availability 100%, p95 5.683s so với 5.604s) vì độ trễ thực tế của alpha ở G4 là ~6.2s, vẫn nhỏ hơn cả 8s lẫn 30s. Do đó, timeout đúng phải dựa trên thời gian cần thiết để failover kịp trước turn deadline của user, chứ không thể dựa vào deadline tổng thể.
3. **Bỏ lọc tool calling khỏi `ladder()`.** Khi bỏ bộ lọc capability khỏi hàm `ladder()` và chạy băng G6, hệ thống ghi nhận `incompatible_routes = 258` và availability tụt từ 100% xuống 89.18%. Đứng dưới góc độ một Product Manager, điều này có nghĩa là đã có 258 khách hàng yêu cầu hoàn tiền (bước bắt buộc phải gọi tool kiểm tra đơn và thực hiện giao dịch ngân hàng) bị chuyển nhầm sang mô hình C-mini giá rẻ không hỗ trợ gọi tool; kết quả là bot trả lời huyên thuyên, không hoàn được tiền và khiến 258 khách hàng bức xúc vì giao dịch thất bại.

## 4. Workflow hoàn tiền

| Executor | completion | crashes | duplicate refunds | duplicate emails | lost refunds | overpaid | wasted LLM / crash |
|---|---:|---:|---:|---:|---:|---:|---:|
| naive | 1.0 | 81 | 128 | 81 | 0 | 1496700 | 1.123 |
| yours | 1.0 | 66 | 0 | 0 | 0 | 0 | 0.303 |

Trả lời:
- Nếu chỉ có Idempotency Key mà không có Checkpoint, hệ thống tránh được trùng tiền ở cổng thanh toán nhưng mỗi khi worker crash, worker mới phải chạy lại toàn bộ quy trình từ bước đầu, gây lãng phí chi phí gọi LLM phân loại/tóm tắt (`wasted_llm_per_crash` tăng cao).
- Ngược lại, nếu chỉ có Checkpoint mà không có Idempotency Key, trong tình huống lệnh thanh toán đã gửi thành công tới ngân hàng nhưng mạng bị timeout trước khi kịp ghi nhận kết quả và lưu checkpoint, worker mới thử lại sẽ thanh toán lần thứ hai gây mất tiền (`duplicate refunds` và `overpaid`). Do đó bắt buộc phải có cả hai.
- Nếu ghi checkpoint *trước* khi gọi payment: trong trường hợp worker ghi checkpoint xong rồi crash ngay trước khi lệnh thanh toán thực sự diễn ra (hoặc lệnh thanh toán bị từ chối), worker mới khởi động lại thấy checkpoint đã tồn tại sẽ tưởng rằng bước thanh toán đã xong và bỏ qua $\rightarrow$ dẫn đến mất tiền hoàn của khách (`lost refunds > 0`).

## 5. Alerting & error budget

| Sự cố | Mong đợi | Naive alerter | Burn-rate alerter | Độ trễ phát hiện |
|---|---|---|---|---:|
| checkout_bug | page | page | page | 27 min |
| provider_outage | page | page | page | 4 min |
| deploy_blip | none | page (false page) | none | — |
| slow_leak | ticket | none (missed) | ticket | 1337 min |
| degraded_evening | page | page | page | 291 min |
| night_spike | none | page (false page) | none | — |
| small_bump | none | page (false page) | none | — |

Error budget 30 ngày: đã tiêu **42.95%**, còn **57.05%**. Quyết định: **Không** đóng băng release (`freeze_releases = False`).

Vì sao `small_bump` (20 phút ở 12% lỗi) **không** nên đánh thức ai lúc 11 giờ trưa?
Bởi vì sự cố này diễn ra trong thời gian rất ngắn (20 phút), chỉ làm tiêu tốn khoảng $20 \times 12\% = 2.4$ phút lỗi tương đương ~0.16% toàn bộ error budget của cả tháng 30 ngày. Nó hoàn toàn không đe dọa đến cam kết SLO 99.5%. Nếu dùng ngưỡng 5 phút đơn lẻ của Naive Alerter, hệ thống sẽ bắn page đánh thức kỹ sư on-call không cần thiết gây hội chứng mệt mỏi vì cảnh báo (*alert fatigue*). Burn-rate alerter đa cửa sổ yêu cầu cả cửa sổ dài 1 giờ và cửa sổ ngắn 5 phút cùng vượt ngưỡng 14.4x (tương đương tiêu hao 2% budget) mới phát lệnh page, do đó đã lọc sạch hiện tượng blip này.

## 6. Postmortem — Băng G2 với client naive (blameless)

*Hình minh họa: `reports/gameday/G2_overload_storm.png` và dữ liệu từ `reports/gameday/naive_G2_overload_storm_timeseries.csv`.*

**Tóm tắt (3 câu):**
Vào thời điểm t=120, deployment chính `alpha` gặp sự cố phần cứng làm mất 75% năng lực tính toán GPU trong vòng 3 phút (t=120 đến t=300). Do client v1 (`NaiveClient`) sử dụng cơ chế retry 3 tầng lồng nhau không có jitter, không có retry budget và không có circuit breaker, lượng request retry dồn dập đã biến sự cố suy giảm tạm thời thành bão retry (*retry storm*), gây nghẽn hoàn toàn hàng đợi FIFO của provider. Mặc dù alpha đã khôi phục 100% năng lực tại t=300, hệ thống vẫn duy trì trạng thái sập siêu bền (*metastable failure*) thêm 153 giây nữa cho tới t=453 mới có thể tự xả hết các request rác cũ.

**Ảnh hưởng:**
Trong suốt sự cố, có 1285 lượt user thất bại (tổng availability tụt xuống 45.60%), kéo dài 155 giây sau khi provider đã phục hồi. Sự cố này gây tiêu tốn lượng ngân sách lỗi tương đương hơn 100% error budget của một ngày vận hành bình thường.

**Timeline** (giây ảo — trích xuất từ `naive_G2_overload_storm_timeseries.csv`):

| t | Sự kiện | Bằng chứng (số) |
|---:|---|---|
| 120 | alpha bắt đầu mất 75% năng lực GPU; hàng đợi xử lý bắt đầu ứ đọng | attempts_alpha = 5 req/s, calls_ok = 7 |
| 136 | Hàng đợi quá tải, xuất hiện lỗi 529 và timeout, bão retry bắt đầu bùng nổ | attempts_alpha vọt lên 53 req/s, calls_ok giảm còn 3 |
| 143 | Đỉnh điểm bão retry: lượng request dồn dập vượt quá sức chịu đựng, hệ thống sập hoàn toàn | attempts_alpha đạt 254 req/s (gấp 12.7x rate limit 20 rps), calls_ok = 0 |
| 220 | Quá tải duy trì liên tục ở mức cực đại trong suốt thời gian GPU suy giảm | attempts_alpha duy trì 140–200 req/s, calls_ok = 0 |
| 300 | alpha hồi phục 100% năng lực GPU, nhưng hệ thống vẫn sập | attempts_alpha = 115 req/s, calls_ok vẫn là 0 |
| 370 | 70 giây sau khi alpha hồi phục, hệ thống vẫn chưa có dấu hiệu phục hồi | attempts_alpha = 13 req/s, calls_ok = 0 (hàng đợi ngập request đã quá hạn) |
| 453 | Hàng đợi FIFO bắt đầu xả xong các request rác mà client đã bỏ rơi; hệ thống hồi phục | attempts_alpha = 7 req/s, calls_ok = 4 (bắt đầu có cuộc gọi thành công) |

**Trigger vs root cause:**
- **Trigger:** Sự cố phần cứng/hạ tầng khiến deployment `alpha` mất 75% GPU tại t=120 trong vòng 180 giây.
- **Root cause:** Khiếm khuyết trong thiết kế kiến trúc phần mềm client v1: 3 tầng retry chồng nhau (tối đa 36 attempt/call), độ trễ cố định, không có jitter, không có retry budget và không có circuit breaker. Khi server chậm lại, lượng retry dồn dập đã khuếch đại lưu lượng lên gấp gần 10 lần (`amplification = 9.904`), khiến tốc độ gửi request luôn vượt xa năng lực xử lý của máy chủ.
- **Vòng lặp metastable:** Provider xử lý hàng đợi theo cơ chế FIFO. Khi client hết kiên nhẫn (deadline 30s) và bỏ cuộc, server vẫn tiếp tục tốn năng lực xử lý các request rác đã quá hạn này. Các request mới đến lại gặp hàng đợi nghẽn nên tiếp tục retry, sinh thêm request rác mới vào cuối hàng đợi. Vòng lặp này tự duy trì và giam cầm hệ thống trong trạng thái tê liệt ngay cả khi năng lực GPU đã trở lại bình thường.

**Điều gì giúp / điều gì làm tệ hơn:**
- *Làm tệ hơn:* Cơ chế retry mù quáng với delay cố định; việc server tiếp tục xử lý các request mà client đã timeout; không có cơ chế failover sang `alpha-eu` hay `beta`.
- *Điều giúp giải quyết:* Cơ chế Circuit Breaker sliding-window phát hiện lỗi và cách ly provider ngay lập tức; Fallback ladder chuyển hướng sang `alpha-eu` và `beta`; Retry Budget giới hạn lượng retry không quá 10%; Full Jitter xóa bỏ hiện tượng đồng bộ xung đột.

**Action items** (cụ thể, có owner, đo được):

| # | Hành động | Loại | Owner | Cách kiểm chứng |
|---|---|---|---|---|
| 1 | Thay thế toàn bộ NaiveClient bằng ResilientClient có Circuit Breaker và Retry Budget trong toàn bộ dịch vụ production. | Mitigate | Đội On-call / Platform | Kiểm tra CI: kịch bản G2 đạt amplification <= 1.2 và availability >= 95%. |
| 2 | Cấu hình deadline propagation (truyền hạn định thời gian) từ client xuống server LLM để server hủy bỏ ngay request khi client đã hết kiên nhẫn, tránh xử lý request mồ côi. | Prevent | Đội Backend Core | Mô phỏng ngắt kết nối client; kiểm tra server lập tức ngừng tính toán token. |
| 3 | Triển khai hệ thống cảnh báo Burn-Rate Alerting đa cửa sổ (1h/5m và 6h/30m) tích hợp PagerDuty. | Detect | Đội SRE | Kiểm tra trên dữ liệu SLI: 0 false page cho blip ngắn, phát hiện sự cố lớn trong vòng <= 5 phút. |

## 7. Một điểm yếu còn lại

**Điểm yếu:**
Khi `alpha` gặp sự cố kéo dài (như ở G6 hoặc G2), client tự động chuyển hướng lượng lớn lưu lượng sang `beta`. Tuy nhiên, chi phí của `beta` đắt hơn 40% (cost 1.4 so với 1.0 của alpha), dẫn đến chi phí vận hành tăng vọt nếu sự cố kéo dài nhiều ngày. Hơn nữa, nếu toàn bộ ngành LLM gặp sự cố diện rộng khiến cả 4 provider cùng bị suy thoái độ trễ, hệ thống sẽ lần lượt trip tất cả các breaker và cạn kiệt fallback.

**Cách khắc phục:**
1. Áp dụng cơ chế **Adaptive Degradation**: khi buộc phải failover sang model đắt tiền hoặc khi toàn bộ hệ thống quá tải, tự động cắt giảm prompt tokens, tắt bớt các tính năng phụ trợ không thiết yếu và ưu tiên trả lời qua Semantic Cache.
2. Thiết lập cơ chế **Load Shedding chủ động** dựa trên hạn mức chi phí (Cost-aware routing) để cân bằng giữa ngân sách và tính sẵn sàng của hệ thống.

## 8. Cache (Part G)

Số liệu trích xuất từ `reports/cache/*.json` (`make cache`):

| Client | availability | faq_availability | cache_hit_ratio | stale_served | wrong_answers | outdated_answers | cost/turn | PASS? |
|---|---:|---:|---:|---:|---:|---:|---:|:---:|
| resilient (không cache) | 0.8373 | 0.8424 | 0.000 | 0 | 0 | 0 | 1.386 | FAIL |
| cached (của bạn) | 0.9124 | 0.9645 | 0.652 | 157 | 0 | 3 | 0.915 | PASS |

| Tham số `cache:` | Giá trị | Vì sao (số liệu nào) |
|---|---:|---|
| similarity_threshold | 0.90 | Ở ngưỡng 0.80 xuất hiện 175 câu trả lời sai (`other_question: 175`). Nâng lên 0.90 loại bỏ hoàn toàn lỗi (`wrong_answers = 0`) trong khi vẫn duy trì cache hit cao (65.2%). |
| ttl_s | 60 | Khi bảng phí ship đổi không báo trước ở t=480, TTL 60s giới hạn `outdated_answers = 3` (đạt chuẩn <= 15). Nếu để TTL 300s, số câu lỗi thời vọt lên 95 câu. |
| max_stale_s | 300 | Sự cố mọi provider sập kéo dài 120 giây (t=240 đến t=360). `max_stale_s = 300` giúp phục vụ 157 câu trả lời stale-if-error, đưa `faq_availability` lên 96.45% (vượt chuẩn >= 93%). |

Thí nghiệm:

1. **Ngưỡng similarity:** Chạy C1 với `similarity_threshold` = 0.80 / 0.90 / 0.97:
   - Ngưỡng 0.80: `hit = 0.659`, `wrong_answers = 175` (`wrong_answers_by_reason: {'other_question': 175}`), `cost/turn = 0.978`. Các câu hỏi có ý nghĩa khác nhau như "thời gian hoàn tiền" và "chính sách hoàn tiền" có cosine ~0.85 bị nhận nhầm lẫn nhau, dẫn đến trả lời sai cho khách.
   - Ngưỡng 0.90: `hit = 0.652`, `wrong_answers = 0`, `cost/turn = 0.915` (tối ưu nhất, cân bằng hoàn hảo giữa tính chính xác và tỷ lệ hit).
   - Ngưỡng 0.97: `hit = 0.579`, `wrong_answers = 0`, `cost/turn = 0.965` (ngưỡng quá chặt khiến nhiều câu hỏi tương đồng bị miss, giảm hiệu quả của cache).
2. **TTL:** Chạy C1 với `ttl_s` = 30 / 60 / 300:
   - TTL 30s: `outdated_answers = 2`, `hit = 0.592`.
   - TTL 60s: `outdated_answers = 3`, `hit = 0.652`.
   - TTL 300s: `outdated_answers = 95`, `hit = 0.731`.
   Webhook chỉ có thể bắn khi hệ thống nội bộ chủ động thông báo (như sự kiện đổi chính sách ở t=150). Đối với các thay đổi bên thứ ba hoặc thay đổi âm thầm không báo trước (như bảng phí ship ở t=480), webhook hoàn toàn bất lực vì không có sự kiện nào được kích hoạt. Do đó, TTL là cơ chế an toàn duy nhất để loại bỏ dữ liệu cũ sau một khoảng thời gian nhất định.
3. **Stale-if-error:** Khi chạy với `max_stale_s: 0` (tắt stale-if-error), `faq_availability` tụt mạnh từ **96.45%** xuống còn **87.33%** (dưới ngưỡng 93%), và `stale_served = 0`. Điều này chứng minh cơ chế stale-if-error đóng vai trò quyết định giúp cứu vãn tính sẵn sàng của dịch vụ trong 120s mọi provider cùng sập.

Trả lời:
- Vì sao câu hỏi cá nhân ("Đơn #48213 của tôi đang ở đâu?") **không** được cache, kể cả khi cache theo từng user?
  Vì dữ liệu cá nhân liên quan đến trạng thái vận đơn và tiền hoàn có tính chất động (stateful), thay đổi liên tục theo thời gian thực (vừa thanh toán xong, trạng thái giao hàng chuyển biến). Nếu cache, người dùng sẽ nhận được thông tin cũ sai lệch. Nguy hiểm hơn, việc lưu trữ thông tin cá nhân trong cache tiềm ẩn rủi ro rò rỉ dữ liệu nghiêm trọng nếu thuật toán embedding nhận diện nhầm hai mã đơn tương tự nhau, dẫn đến để lộ thông tin riêng tư của khách hàng này cho khách hàng khác.
- Trong lúc mọi provider sập, dashboard vẫn xanh nhờ cache. Bạn sẽ alert dựa trên số nào để on-call vẫn biết có sự cố?
  Hệ thống giám sát không được chỉ dựa vào availability ở tầng người dùng cuối (*end-user availability*). Thay vào đó, cần thiết lập cảnh báo dựa trên:
  1. Tỷ lệ **Backend Origin Error Rate** (tỷ lệ lỗi thực tế từ các cuộc gọi trực tiếp xuống provider LLM vượt quá 10%).
  2. Số lượng hoặc tỷ lệ **Stale Responses Served** (chỉ số `stale_served > 0` hoặc tăng đột biến chứng tỏ hệ thống đang phải dùng giải pháp tình thế).
  3. Trạng thái của **Circuit Breakers** (bắn cảnh báo ngay khi có bất kỳ breaker nào chuyển sang trạng thái `OPEN`).
