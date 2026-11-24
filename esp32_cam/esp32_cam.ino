/*
 * ESP32-CAM (AI-Thinker, OV2640) — camera nhận diện biển số cho cả cổng vào và cổng ra.
 *
 * Server (pc_server) chủ động lấy ảnh khi Pi báo có xe ở cổng:
 *   GET http://<ip>/?key=CAM_KEY                   -> TRANG CÀI ĐẶT: lật ảnh, độ phân giải, chất lượng, độ sáng (lưu luôn)
 *   GET http://<ip>/capture?key=CAM_KEY            -> 1 ảnh JPEG (độ phân giải cao, đọc biển rõ)
 *   GET http://<ip>/status?key=CAM_KEY             -> JSON tình trạng + cài đặt hiện tại
 *   GET http://<ip>/control?key=CAM_KEY&flash=0..255  (đèn flash GPIO4; 0 = tắt; không lưu)
 *   GET http://<ip>/control?key=CAM_KEY&vflip=0|1&hmirror=0|1&size=sxga&quality=8&brightness=0&contrast=1&ae=0
 *       -> LƯU vào bộ nhớ ESP32 (khởi động lại vẫn giữ). reset=1 về mặc định. Đổi size thì ESP32 tự khởi động lại.
 *   GET http://<ip>/aim?key=CAM_KEY&gate=in|out    -> ĐỘNG CƠ BƯỚC xoay camera về cổng (chờ quay xong mới trả lời)
 *       &steps=±N (nhích tay) | &set=in|out (lưu vị trí hiện tại làm vị trí cổng) | &zero=1 (đặt vị trí hiện tại = 0)
 *   GET http://<ip>:81/stream?key=CAM_KEY          -> luồng MJPEG để xem/căn camera — CHỈ khi STREAM_ENABLED = true
 *       (mặc định tắt: cổng 81 không mở, camera chỉ chụp khi được gọi /capture)
 *
 * Động cơ bước 28BYJ-48 + mạch ULN2003 (xoay camera giữa cổng vào và cổng ra):
 *   IN1 -> GPIO14, IN2 -> GPIO15, IN3 -> GPIO13, IN4 -> GPIO12 (các chân của khe thẻ SD — KHÔNG cắm thẻ nhớ)
 *   ULN2003 "+" -> 5V (cùng nguồn 5V/2A với ESP32-CAM), "-" -> GND chung. Vị trí được lưu, mất điện vẫn nhớ.
 *   Quay đi rồi quay ngược lại (không quay vòng tròn) -> dây camera không bị xoắn.
 *
 * Nạp code (Arduino IDE):
 *   1. Boards Manager: cài "esp32 by Espressif Systems" (bản 3.x).
 *   2. Tools -> Board: "AI Thinker ESP32-CAM"; Partition Scheme: "Huge APP (3MB No OTA)"; PSRAM: Enabled.
 *   3. Chép secrets.example.h thành secrets.h, điền WIFI_SSID / WIFI_PASS / CAM_KEY, nạp qua mạch FTDI (nối IO0 với GND khi nạp, rút ra rồi nhấn RESET).
 *   4. Mở Serial Monitor 115200 để xem IP, rồi nhập http://<ip> vào trang Thiết bị của dashboard.
 *
 * Nguồn: dùng 5V/2A ổn định (ESP32-CAM sụt áp khi phát WiFi + bật flash sẽ tự khởi động lại).
 */
#include "esp_camera.h"
#include "esp_http_server.h"
#include <Preferences.h>
#include <WiFi.h>

// ------------------------------------------------------------ cấu hình
#include "secrets.h"   // WIFI_SSID, WIFI_PASS, CAM_KEY — chép secrets.example.h thành secrets.h rồi điền
// Giá trị MẶC ĐỊNH (lần đầu chạy / sau reset=1). Đổi lúc chạy ở trang http://<ip>/?key=... -> lưu vào bộ nhớ ESP32.
// Độ phân giải: biển trên xe mô hình rất nhỏ -> SXGA (1280x1024); UXGA (1600x1200) nét hơn nhưng chụp chậm hơn
const framesize_t FRAME_SIZE = FRAMESIZE_SXGA;
const int JPEG_QUALITY = 8;                         // 4..63, càng nhỏ càng nét (ảnh càng nặng). <6 dễ thiếu bộ nhớ
const int BRIGHTNESS = 0;                           // -2..2
const int CONTRAST = 1;                             // -2..2 (tăng nhẹ -> chữ đen trên nền trắng rõ hơn)
const int AE_LEVEL = 0;                             // -2..2 bù sáng (biển bị cháy sáng -> giảm)
// Hướng ảnh mặc định (đổi được trên trang cài đặt, không cần nạp lại):
//   ảnh lộn ngược (xoay 180°): FLIP_VERTICAL = true,  MIRROR_HORIZONTAL = true
//   chữ bị ngược trái-phải   : FLIP_VERTICAL = false, MIRROR_HORIZONTAL = true
//   chỉ bị lật trên-dưới     : FLIP_VERTICAL = true,  MIRROR_HORIZONTAL = false
const bool FLIP_VERTICAL = false;
const bool MIRROR_HORIZONTAL = true;                // ảnh bị ngược như soi gương -> lật trái-phải
const bool FLASH_ON_CAPTURE = false;                // luôn bật đèn flash khi chụp (server cũng tự bật được qua /control)
const int FLASH_LEVEL = 60;                         // 0..255 (đèn rất sáng, để thấp tránh lóa biển)
// Luồng MJPEG cổng 81: false = KHÔNG mở stream khi khởi động (chỉ chụp ảnh khi được gọi /capture).
// Server không cần stream. Chỉ bật true khi muốn xem trực tiếp để căn góc (plate_cam_test.py --stream).
const bool STREAM_ENABLED = false;

// Động cơ bước xoay camera (false = camera đứng yên, /aim chỉ trả lời "ok")
const bool STEPPER_ENABLED = true;
const int STEPPER_PINS[4] = {14, 15, 13, 12};      // IN1..IN4 của ULN2003
const int STEPS_PER_REV = 2048;                     // 28BYJ-48 chạy cả bước (2 cuộn): 2048 bước / vòng
const int STEP_DELAY_MS = 3;                        // ms / bước: 3 = ~10 vòng/phút, êm. Rung tại chỗ -> tăng 4..5
const int DEFAULT_IN_POS = 0;                       // vị trí (bước) nhìn cổng vào
const int DEFAULT_OUT_POS = STEPS_PER_REV / 2;      // vị trí nhìn cổng ra: quay 180° (chỉnh trên trang cài đặt)
const int AIM_SETTLE_MS = 350;                      // quay xong chờ camera hết rung rồi mới cho chụp

// ------------------------------------------------------------ chân AI-Thinker
#define PWDN_GPIO_NUM 32
#define RESET_GPIO_NUM -1
#define XCLK_GPIO_NUM 0
#define SIOD_GPIO_NUM 26
#define SIOC_GPIO_NUM 27
#define Y9_GPIO_NUM 35
#define Y8_GPIO_NUM 34
#define Y7_GPIO_NUM 39
#define Y6_GPIO_NUM 36
#define Y5_GPIO_NUM 21
#define Y4_GPIO_NUM 19
#define Y3_GPIO_NUM 18
#define Y2_GPIO_NUM 5
#define VSYNC_GPIO_NUM 25
#define HREF_GPIO_NUM 23
#define PCLK_GPIO_NUM 22
#define FLASH_GPIO_NUM 4

httpd_handle_t web_httpd = NULL;
httpd_handle_t stream_httpd = NULL;
SemaphoreHandle_t cam_lock;   // /capture và /stream dùng chung cảm biến
uint32_t captures = 0;

void set_flash(int level) { analogWrite(FLASH_GPIO_NUM, level); }

// ------------------------------------------------------------ cài đặt lưu trong bộ nhớ (NVS)
Preferences prefs;
struct Settings { int size, quality, vflip, hmirror, brightness, contrast, ae; } cfg;

struct SizeName { const char *name; framesize_t size; };
const SizeName SIZES[] = {{"vga", FRAMESIZE_VGA}, {"svga", FRAMESIZE_SVGA}, {"xga", FRAMESIZE_XGA},
                          {"hd", FRAMESIZE_HD}, {"sxga", FRAMESIZE_SXGA}, {"uxga", FRAMESIZE_UXGA}};

const char *size_name(int fs) {
  for (auto &z : SIZES) if (z.size == fs) return z.name;
  return "?";
}

void load_settings() {
  cfg.size = prefs.getInt("size", FRAME_SIZE);
  cfg.quality = prefs.getInt("quality", JPEG_QUALITY);
  cfg.vflip = prefs.getInt("vflip", FLIP_VERTICAL);
  cfg.hmirror = prefs.getInt("hmirror", MIRROR_HORIZONTAL);
  cfg.brightness = prefs.getInt("bright", BRIGHTNESS);
  cfg.contrast = prefs.getInt("contrast", CONTRAST);
  cfg.ae = prefs.getInt("ae", AE_LEVEL);
}

void save_settings() {
  prefs.putInt("size", cfg.size);
  prefs.putInt("quality", cfg.quality);
  prefs.putInt("vflip", cfg.vflip);
  prefs.putInt("hmirror", cfg.hmirror);
  prefs.putInt("bright", cfg.brightness);
  prefs.putInt("contrast", cfg.contrast);
  prefs.putInt("ae", cfg.ae);
}

void apply_sensor() {
  sensor_t *s = esp_camera_sensor_get();
  s->set_quality(s, cfg.quality);
  s->set_vflip(s, cfg.vflip);
  s->set_hmirror(s, cfg.hmirror);
  s->set_brightness(s, cfg.brightness);
  s->set_contrast(s, cfg.contrast);
  s->set_ae_level(s, cfg.ae);
}

// ------------------------------------------------------------ động cơ bước
const uint8_t FULL_STEP[4][4] = {{1, 1, 0, 0}, {0, 1, 1, 0}, {0, 0, 1, 1}, {1, 0, 0, 1}};
int motor_pos = 0, in_pos = DEFAULT_IN_POS, out_pos = DEFAULT_OUT_POS;
const char *aimed = "?";

void coils(const uint8_t *v) { for (int i = 0; i < 4; i++) digitalWrite(STEPPER_PINS[i], v[i]); }
void coils_off() { static const uint8_t off[4] = {0, 0, 0, 0}; coils(off); }

// quay tới vị trí tuyệt đối; ngắt điện cuộn dây khi xong (hộp số 1:64 tự giữ, động cơ không nóng)
int move_to(int target) {
  int n = 0;
  while (motor_pos != target) {
    motor_pos += (target > motor_pos) ? 1 : -1;
    coils(FULL_STEP[((motor_pos % 4) + 4) % 4]);
    delay(STEP_DELAY_MS);
    n++;
  }
  coils_off();
  prefs.putInt("pos", motor_pos);   // nhớ vị trí qua lần mất điện
  return n;
}

void stepper_begin() {
  for (int i = 0; i < 4; i++) { pinMode(STEPPER_PINS[i], OUTPUT); digitalWrite(STEPPER_PINS[i], LOW); }
  motor_pos = prefs.getInt("pos", DEFAULT_IN_POS);
  in_pos = prefs.getInt("in_pos", DEFAULT_IN_POS);
  out_pos = prefs.getInt("out_pos", DEFAULT_OUT_POS);
  aimed = motor_pos == in_pos ? "in" : motor_pos == out_pos ? "out" : "?";
}

// ------------------------------------------------------------ kiểm tra khóa
bool authorized(httpd_req_t *req) {
  if (strlen(CAM_KEY) == 0) return true;
  char query[200], key[64];
  if (httpd_req_get_url_query_str(req, query, sizeof(query)) == ESP_OK &&
      httpd_query_key_value(query, "key", key, sizeof(key)) == ESP_OK && strcmp(key, CAM_KEY) == 0)
    return true;
  httpd_resp_set_status(req, "401 Unauthorized");
  httpd_resp_sendstr(req, "sai khoa");
  return false;
}

// ------------------------------------------------------------ /capture
esp_err_t capture_handler(httpd_req_t *req) {
  if (!authorized(req)) return ESP_OK;
  xSemaphoreTake(cam_lock, portMAX_DELAY);
  if (FLASH_ON_CAPTURE) { set_flash(FLASH_LEVEL); delay(120); }
  // bỏ 1 khung cũ trong bộ đệm để ảnh là khoảnh khắc hiện tại (xe đang ở cổng)
  camera_fb_t *fb = esp_camera_fb_get();
  if (fb) esp_camera_fb_return(fb);
  fb = esp_camera_fb_get();
  if (FLASH_ON_CAPTURE) set_flash(0);
  if (!fb) {
    xSemaphoreGive(cam_lock);
    httpd_resp_send_500(req);
    return ESP_FAIL;
  }
  httpd_resp_set_type(req, "image/jpeg");
  httpd_resp_set_hdr(req, "Cache-Control", "no-store");
  esp_err_t res = httpd_resp_send(req, (const char *)fb->buf, fb->len);
  esp_camera_fb_return(fb);
  xSemaphoreGive(cam_lock);
  captures++;
  return res;
}

// ------------------------------------------------------------ /status, /control
esp_err_t status_handler(httpd_req_t *req) {
  if (!authorized(req)) return ESP_OK;
  char json[400];
  snprintf(json, sizeof(json),
           "{\"size\":\"%s\",\"quality\":%d,\"vflip\":%d,\"hmirror\":%d,\"brightness\":%d,\"contrast\":%d,"
           "\"ae\":%d,\"stepper\":%d,\"gate\":\"%s\",\"pos\":%d,\"in_pos\":%d,\"out_pos\":%d,"
           "\"rssi\":%d,\"uptime_s\":%lu,\"captures\":%lu,\"heap\":%u,\"psram\":%u}",
           size_name(cfg.size), cfg.quality, cfg.vflip, cfg.hmirror, cfg.brightness, cfg.contrast, cfg.ae,
           STEPPER_ENABLED, aimed, motor_pos, in_pos, out_pos,
           WiFi.RSSI(), millis() / 1000, (unsigned long)captures, ESP.getFreeHeap(), ESP.getFreePsram());
  httpd_resp_set_type(req, "application/json");
  return httpd_resp_sendstr(req, json);
}

esp_err_t control_handler(httpd_req_t *req) {
  if (!authorized(req)) return ESP_OK;
  char query[200], val[16];
  bool changed = false, restart = false;
  if (httpd_req_get_url_query_str(req, query, sizeof(query)) == ESP_OK) {
    auto get = [&](const char *k) { return httpd_query_key_value(query, k, val, sizeof(val)) == ESP_OK; };
    if (get("flash")) set_flash(constrain(atoi(val), 0, 255));   // flash không lưu
    if (get("vflip")) { cfg.vflip = atoi(val) ? 1 : 0; changed = true; }
    if (get("hmirror")) { cfg.hmirror = atoi(val) ? 1 : 0; changed = true; }
    if (get("quality")) { cfg.quality = constrain(atoi(val), 4, 63); changed = true; }
    if (get("brightness")) { cfg.brightness = constrain(atoi(val), -2, 2); changed = true; }
    if (get("contrast")) { cfg.contrast = constrain(atoi(val), -2, 2); changed = true; }
    if (get("ae")) { cfg.ae = constrain(atoi(val), -2, 2); changed = true; }
    if (get("size")) {
      for (auto &z : SIZES)
        if (strcmp(val, z.name) == 0 && z.size != cfg.size) { cfg.size = z.size; changed = restart = true; }
    }
    if (get("reset")) {   // về mặc định cài đặt ảnh; GIỮ vị trí động cơ bước
      for (const char *k : {"size", "quality", "vflip", "hmirror", "bright", "contrast", "ae"}) prefs.remove(k);
      load_settings(); changed = restart = true;
    }
  }
  if (changed) {
    save_settings();
    xSemaphoreTake(cam_lock, portMAX_DELAY);
    apply_sensor();
    xSemaphoreGive(cam_lock);
  }
  httpd_resp_sendstr(req, restart ? "ok, dang khoi dong lai" : "ok");
  if (restart) { delay(300); ESP.restart(); }   // bộ đệm ảnh cấp theo độ phân giải -> phải khởi động lại
  return ESP_OK;
}

// ------------------------------------------------------------ /aim: xoay camera về cổng
esp_err_t aim_handler(httpd_req_t *req) {
  if (!authorized(req)) return ESP_OK;
  char query[200], val[16];
  int moved = 0;
  uint32_t t0 = millis();
  if (STEPPER_ENABLED && httpd_req_get_url_query_str(req, query, sizeof(query)) == ESP_OK) {
    auto get = [&](const char *k) { return httpd_query_key_value(query, k, val, sizeof(val)) == ESP_OK; };
    if (get("gate")) {
      bool out = strcmp(val, "out") == 0;
      moved = move_to(out ? out_pos : in_pos);
      aimed = out ? "out" : "in";
      if (moved) delay(AIM_SETTLE_MS);
    } else if (get("steps")) {                       // nhích tay để căn góc
      moved = move_to(motor_pos + constrain(atoi(val), -STEPS_PER_REV, STEPS_PER_REV));
      aimed = "?";
    } else if (get("set")) {                         // lưu vị trí hiện tại làm vị trí của cổng
      if (strcmp(val, "out") == 0) { out_pos = motor_pos; prefs.putInt("out_pos", out_pos); aimed = "out"; }
      else { in_pos = motor_pos; prefs.putInt("in_pos", in_pos); aimed = "in"; }
    } else if (get("zero")) {                        // coi vị trí hiện tại là 0 (dời cả 2 vị trí cổng theo)
      in_pos -= motor_pos; out_pos -= motor_pos; motor_pos = 0;
      prefs.putInt("pos", 0); prefs.putInt("in_pos", in_pos); prefs.putInt("out_pos", out_pos);
    }
  }
  char json[160];
  snprintf(json, sizeof(json), "{\"enabled\":%d,\"gate\":\"%s\",\"pos\":%d,\"in_pos\":%d,\"out_pos\":%d,\"moved\":%d,\"ms\":%lu}",
           STEPPER_ENABLED, aimed, motor_pos, in_pos, out_pos, moved, (unsigned long)(millis() - t0));
  httpd_resp_set_type(req, "application/json");
  return httpd_resp_sendstr(req, json);
}

// ------------------------------------------------------------ / trang cài đặt
const char PAGE[] = R"HTML(<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>ESP32-CAM</title><style>
body{font-family:sans-serif;background:#111;color:#eee;margin:0;padding:12px}img{max-width:100%;border-radius:8px;background:#222;min-height:120px}
.g{display:flex;flex-wrap:wrap;gap:8px;margin:10px 0;align-items:center}button,select{padding:8px 12px;border-radius:6px;border:0;background:#2b6;color:#fff;font-size:15px}
select{background:#333}label{min-width:100px}#st{color:#9c9;font-size:13px;white-space:pre-wrap;word-break:break-all}</style></head><body>
<h3>ESP32-CAM - cài đặt camera biển số</h3><img id="v" alt="đang chụp...">
<div class="g"><button onclick="t('vflip')">Lật trên-dưới</button><button onclick="t('hmirror')">Lật trái-phải (gương)</button>
<button onclick="snap()">Chụp lại</button></div>
<div class="g"><label>Độ phân giải</label><select id="size" onchange="c('size',this.value)">
<option value="vga">VGA 640x480</option><option value="svga">SVGA 800x600</option><option value="xga">XGA 1024x768</option>
<option value="hd">HD 1280x720</option><option value="sxga">SXGA 1280x1024</option><option value="uxga">UXGA 1600x1200</option></select>
<label>Chất lượng</label><select id="quality" onchange="c('quality',this.value)">
<option value="6">6 (nét nhất)</option><option value="8">8</option><option value="10">10</option><option value="12">12</option><option value="15">15 (nhẹ)</option></select></div>
<div class="g"><label>Độ sáng</label><select id="brightness" onchange="c('brightness',this.value)"></select>
<label>Tương phản</label><select id="contrast" onchange="c('contrast',this.value)"></select>
<label>Bù sáng</label><select id="ae" onchange="c('ae',this.value)"></select></div>
<h4>Động cơ bước xoay camera <span id="pos"></span></h4>
<div class="g"><button onclick="a('gate=in')">Nhìn cổng VÀO</button><button onclick="a('gate=out')">Nhìn cổng RA</button></div>
<div class="g"><label>Nhích</label><button onclick="a('steps=-128')">-128</button><button onclick="a('steps=-16')">-16</button>
<button onclick="a('steps=16')">+16</button><button onclick="a('steps=128')">+128</button></div>
<div class="g"><button style="background:#36c" onclick="a('set=in')">Lưu chỗ này = cổng VÀO</button>
<button style="background:#36c" onclick="a('set=out')">Lưu chỗ này = cổng RA</button></div>
<div class="g"><button onclick="c('flash',80)">Flash bật</button><button onclick="c('flash',0)">Flash tắt</button>
<button style="background:#a33" onclick="confirm('Về cài đặt mặc định?')&&c('reset',1)">Mặc định</button></div><div id="st"></div>
<script>const K=encodeURIComponent(new URLSearchParams(location.search).get('key')||'');let S={};
['brightness','contrast','ae'].forEach(id=>{for(let v=-2;v<=2;v++)document.getElementById(id).add(new Option(v,v))});
function snap(){document.getElementById('v').src='/capture?key='+K+'&_='+Date.now()}
async function load(){S=await(await fetch('/status?key='+K)).json();
['size','quality','brightness','contrast','ae'].forEach(k=>{const e=document.getElementById(k);
if(![...e.options].some(o=>o.value==S[k]))e.add(new Option(S[k],S[k]));e.value=S[k]});
document.getElementById('st').textContent=JSON.stringify(S);
document.getElementById('pos').textContent=S.stepper?'(vị trí '+S.pos+', vào='+S.in_pos+', ra='+S.out_pos+', đang nhìn: '+S.gate+')':'(đang tắt)'}
async function a(q){document.getElementById('pos').textContent='(đang quay...)';await fetch('/aim?key='+K+'&'+q);await load();snap()}
async function c(k,v){const r=await(await fetch('/control?key='+K+'&'+k+'='+v)).text();
if(r.includes('khoi dong')){document.getElementById('st').textContent='Đang khởi động lại...';setTimeout(()=>location.reload(),7000);return}
await load();setTimeout(snap,400)}
function t(k){c(k,S[k]?0:1)}
load().then(snap)</script></body></html>)HTML";

esp_err_t index_handler(httpd_req_t *req) {
  if (!authorized(req)) return ESP_OK;
  httpd_resp_set_type(req, "text/html; charset=utf-8");
  return httpd_resp_send(req, PAGE, HTTPD_RESP_USE_STRLEN);
}

// ------------------------------------------------------------ :81/stream (xem trực tiếp để căn camera)
#define BOUNDARY "frame"
esp_err_t stream_handler(httpd_req_t *req) {
  if (!authorized(req)) return ESP_OK;
  httpd_resp_set_type(req, "multipart/x-mixed-replace;boundary=" BOUNDARY);
  char head[80];
  while (true) {
    xSemaphoreTake(cam_lock, portMAX_DELAY);
    camera_fb_t *fb = esp_camera_fb_get();
    if (!fb) { xSemaphoreGive(cam_lock); return ESP_FAIL; }
    size_t n = snprintf(head, sizeof(head), "\r\n--" BOUNDARY "\r\nContent-Type: image/jpeg\r\nContent-Length: %u\r\n\r\n", fb->len);
    esp_err_t res = httpd_resp_send_chunk(req, head, n);
    if (res == ESP_OK) res = httpd_resp_send_chunk(req, (const char *)fb->buf, fb->len);
    esp_camera_fb_return(fb);
    xSemaphoreGive(cam_lock);   // nhả giữa các khung để /capture chen vào được
    if (res != ESP_OK) break;
    delay(80);                  // ~10 fps là đủ để căn góc, đỡ nóng
  }
  return ESP_OK;
}

void start_servers() {
  httpd_config_t hc = HTTPD_DEFAULT_CONFIG();
  hc.server_port = 80;
  hc.ctrl_port = 32768;
  hc.max_uri_handlers = 8;
  hc.recv_wait_timeout = 10;   // /aim có thể mất ~3 s khi quay 180°
  hc.send_wait_timeout = 10;
  httpd_uri_t idx = {"/", HTTP_GET, index_handler, NULL};
  httpd_uri_t aim = {"/aim", HTTP_GET, aim_handler, NULL};
  httpd_uri_t cap = {"/capture", HTTP_GET, capture_handler, NULL};
  httpd_uri_t st = {"/status", HTTP_GET, status_handler, NULL};
  httpd_uri_t ctl = {"/control", HTTP_GET, control_handler, NULL};
  if (httpd_start(&web_httpd, &hc) == ESP_OK) {
    httpd_register_uri_handler(web_httpd, &idx);
    httpd_register_uri_handler(web_httpd, &aim);
    httpd_register_uri_handler(web_httpd, &cap);
    httpd_register_uri_handler(web_httpd, &st);
    httpd_register_uri_handler(web_httpd, &ctl);
  }
  if (!STREAM_ENABLED) return;   // không mở cổng 81
  hc.server_port = 81;
  hc.ctrl_port = 32769;
  httpd_uri_t stream = {"/stream", HTTP_GET, stream_handler, NULL};
  if (httpd_start(&stream_httpd, &hc) == ESP_OK) httpd_register_uri_handler(stream_httpd, &stream);
}

// ------------------------------------------------------------ khởi động
void setup() {
  Serial.begin(115200);
  pinMode(FLASH_GPIO_NUM, OUTPUT);
  set_flash(0);
  cam_lock = xSemaphoreCreateMutex();
  prefs.begin("cam", false);
  load_settings();
  if (STEPPER_ENABLED) stepper_begin();

  camera_config_t c = {};
  c.ledc_channel = LEDC_CHANNEL_0;
  c.ledc_timer = LEDC_TIMER_0;
  c.pin_d0 = Y2_GPIO_NUM; c.pin_d1 = Y3_GPIO_NUM; c.pin_d2 = Y4_GPIO_NUM; c.pin_d3 = Y5_GPIO_NUM;
  c.pin_d4 = Y6_GPIO_NUM; c.pin_d5 = Y7_GPIO_NUM; c.pin_d6 = Y8_GPIO_NUM; c.pin_d7 = Y9_GPIO_NUM;
  c.pin_xclk = XCLK_GPIO_NUM; c.pin_pclk = PCLK_GPIO_NUM; c.pin_vsync = VSYNC_GPIO_NUM; c.pin_href = HREF_GPIO_NUM;
  c.pin_sccb_sda = SIOD_GPIO_NUM; c.pin_sccb_scl = SIOC_GPIO_NUM;
  c.pin_pwdn = PWDN_GPIO_NUM; c.pin_reset = RESET_GPIO_NUM;
  c.xclk_freq_hz = 20000000;
  c.pixel_format = PIXFORMAT_JPEG;
  c.frame_size = (framesize_t)cfg.size;
  c.jpeg_quality = cfg.quality;
  c.fb_count = psramFound() ? 2 : 1;
  c.fb_location = psramFound() ? CAMERA_FB_IN_PSRAM : CAMERA_FB_IN_DRAM;
  c.grab_mode = CAMERA_GRAB_LATEST;
  if (!psramFound()) { c.frame_size = FRAMESIZE_SVGA; cfg.size = FRAMESIZE_SVGA; }

  if (esp_camera_init(&c) != ESP_OK) {
    // độ phân giải / chất lượng quá cao so với bộ nhớ -> lùi về XGA, chất lượng 10 rồi thử lại
    Serial.println("Loi khoi tao camera -> lui ve XGA q10 va khoi dong lai");
    cfg.size = FRAMESIZE_XGA; cfg.quality = 10; save_settings();
    delay(1000);
    ESP.restart();
  }
  sensor_t *s = esp_camera_sensor_get();
  s->set_whitebal(s, 1);
  s->set_awb_gain(s, 1);
  s->set_exposure_ctrl(s, 1);
  s->set_gain_ctrl(s, 1);
  s->set_sharpness(s, 1);      // chữ trên biển nét hơn (một số module bỏ qua)
  s->set_lenc(s, 1);           // sửa tối góc ống kính
  s->set_bpc(s, 1);            // sửa điểm ảnh chết đen
  s->set_wpc(s, 1);            // sửa điểm ảnh chết trắng
  s->set_raw_gma(s, 1);        // gamma -> vùng tối rõ hơn
  s->set_dcw(s, 1);
  s->set_gainceiling(s, GAINCEILING_4X);   // giới hạn khuếch đại -> ít nhiễu hạt khi thiếu sáng (tối quá thì dùng flash)
  apply_sensor();              // hướng ảnh, chất lượng, độ sáng... đã lưu
  Serial.printf("Camera: %s q%d vflip=%d hmirror=%d\n", size_name(cfg.size), cfg.quality, cfg.vflip, cfg.hmirror);
  if (STEPPER_ENABLED) Serial.printf("Dong co buoc: vi tri %d (vao=%d, ra=%d)\n", motor_pos, in_pos, out_pos);

  WiFi.mode(WIFI_STA);
  WiFi.setSleep(false);        // tắt tiết kiệm điện -> phản hồi nhanh, ổn định
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  Serial.print("Dang ket noi WiFi");
  for (int i = 0; WiFi.status() != WL_CONNECTED; i++) {
    delay(500);
    Serial.print(".");
    if (i > 60) ESP.restart();
  }
  String ip = WiFi.localIP().toString();
  Serial.printf("\nIP: http://%s\n", ip.c_str());
  if (STREAM_ENABLED) Serial.printf("Stream: http://%s:81/stream?key=<CAM_KEY>\n", ip.c_str());
  else Serial.println("Stream: TAT (STREAM_ENABLED = false) - chi chup khi duoc goi /capture");
  Serial.printf("Trang cai dat: http://%s/?key=<CAM_KEY>\n", ip.c_str());
  start_servers();
}

void loop() {
  // mất WiFi thì tự kết nối lại
  if (WiFi.status() != WL_CONNECTED) {
    WiFi.reconnect();
    delay(3000);
  }
  delay(1000);
}
