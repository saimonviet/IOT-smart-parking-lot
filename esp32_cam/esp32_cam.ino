/*
 * ESP32-CAM (AI-Thinker, OV2640) — camera nhận diện biển số cho cả cổng vào và cổng ra.
 *
 * Server (pc_server) chủ động lấy ảnh khi Pi báo có xe ở cổng:
 *   GET http://<ip>/capture?key=CAM_KEY            -> 1 ảnh JPEG (độ phân giải cao, đọc biển rõ)
 *   GET http://<ip>/status?key=CAM_KEY             -> JSON tình trạng
 *   GET http://<ip>/control?key=CAM_KEY&flash=0..255  (đèn flash GPIO4; 0 = tắt)
 *   GET http://<ip>:81/stream?key=CAM_KEY          -> luồng MJPEG để xem/căn camera
 *
 * Nạp code (Arduino IDE):
 *   1. Boards Manager: cài "esp32 by Espressif Systems" (bản 3.x).
 *   2. Tools -> Board: "AI Thinker ESP32-CAM"; Partition Scheme: "Huge APP (3MB No OTA)"; PSRAM: Enabled.
 *   3. Sửa WIFI_SSID / WIFI_PASS / CAM_KEY bên dưới, nạp qua mạch FTDI (nối IO0 với GND khi nạp, rút ra rồi nhấn RESET).
 *   4. Mở Serial Monitor 115200 để xem IP, rồi nhập http://<ip> vào trang Thiết bị của dashboard.
 *
 * Nguồn: dùng 5V/2A ổn định (ESP32-CAM sụt áp khi phát WiFi + bật flash sẽ tự khởi động lại).
 */
#include "esp_camera.h"
#include "esp_http_server.h"
#include <WiFi.h>

// ------------------------------------------------------------ cấu hình
const char *WIFI_SSID = "TEN_WIFI";
const char *WIFI_PASS = "MAT_KHAU_WIFI";
const char *CAM_KEY   = "doi-khoa-nay-16ky-tu";   // khớp "Khóa" trên trang Thiết bị; "" = không kiểm tra
// Độ phân giải: biển số trên xe mô hình rất nhỏ -> dùng XGA (1024x768) hoặc SXGA (1280x1024)
const framesize_t FRAME_SIZE = FRAMESIZE_XGA;
const int JPEG_QUALITY = 10;                        // 4..63, càng nhỏ càng nét (ảnh càng nặng)
const bool FLASH_ON_CAPTURE = false;                // bật đèn flash khi chụp (bãi tối)
const int FLASH_LEVEL = 60;                         // 0..255 (đèn rất sáng, để thấp tránh lóa biển)

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

// ------------------------------------------------------------ kiểm tra khóa
bool authorized(httpd_req_t *req) {
  if (strlen(CAM_KEY) == 0) return true;
  char query[160], key[64];
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
  char json[200];
  sensor_t *s = esp_camera_sensor_get();
  snprintf(json, sizeof(json),
           "{\"framesize\":%d,\"quality\":%d,\"rssi\":%d,\"uptime_s\":%lu,\"captures\":%lu,\"heap\":%u}",
           s->status.framesize, s->status.quality, WiFi.RSSI(), millis() / 1000, captures, ESP.getFreeHeap());
  httpd_resp_set_type(req, "application/json");
  return httpd_resp_sendstr(req, json);
}

esp_err_t control_handler(httpd_req_t *req) {
  if (!authorized(req)) return ESP_OK;
  char query[160], val[16];
  if (httpd_req_get_url_query_str(req, query, sizeof(query)) == ESP_OK &&
      httpd_query_key_value(query, "flash", val, sizeof(val)) == ESP_OK) {
    set_flash(constrain(atoi(val), 0, 255));
  }
  return httpd_resp_sendstr(req, "ok");
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
  httpd_config_t cfg = HTTPD_DEFAULT_CONFIG();
  cfg.server_port = 80;
  cfg.ctrl_port = 32768;
  httpd_uri_t cap = {"/capture", HTTP_GET, capture_handler, NULL};
  httpd_uri_t st = {"/status", HTTP_GET, status_handler, NULL};
  httpd_uri_t ctl = {"/control", HTTP_GET, control_handler, NULL};
  if (httpd_start(&web_httpd, &cfg) == ESP_OK) {
    httpd_register_uri_handler(web_httpd, &cap);
    httpd_register_uri_handler(web_httpd, &st);
    httpd_register_uri_handler(web_httpd, &ctl);
  }
  cfg.server_port = 81;
  cfg.ctrl_port = 32769;
  httpd_uri_t stream = {"/stream", HTTP_GET, stream_handler, NULL};
  if (httpd_start(&stream_httpd, &cfg) == ESP_OK) httpd_register_uri_handler(stream_httpd, &stream);
}

// ------------------------------------------------------------ khởi động
void setup() {
  Serial.begin(115200);
  pinMode(FLASH_GPIO_NUM, OUTPUT);
  set_flash(0);
  cam_lock = xSemaphoreCreateMutex();

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
  c.frame_size = FRAME_SIZE;
  c.jpeg_quality = JPEG_QUALITY;
  c.fb_count = psramFound() ? 2 : 1;
  c.fb_location = psramFound() ? CAMERA_FB_IN_PSRAM : CAMERA_FB_IN_DRAM;
  c.grab_mode = CAMERA_GRAB_LATEST;
  if (!psramFound()) c.frame_size = FRAMESIZE_SVGA;

  if (esp_camera_init(&c) != ESP_OK) {
    Serial.println("Loi khoi tao camera -> khoi dong lai");
    delay(1000);
    ESP.restart();
  }
  sensor_t *s = esp_camera_sensor_get();
  s->set_whitebal(s, 1);
  s->set_exposure_ctrl(s, 1);
  s->set_gain_ctrl(s, 1);
  s->set_sharpness(s, 1);      // chữ trên biển nét hơn (một số module bỏ qua)
  // s->set_vflip(s, 1); s->set_hmirror(s, 1);   // bật nếu ảnh bị lật

  WiFi.mode(WIFI_STA);
  WiFi.setSleep(false);        // tắt tiết kiệm điện -> phản hồi nhanh, ổn định
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  Serial.print("Dang ket noi WiFi");
  for (int i = 0; WiFi.status() != WL_CONNECTED; i++) {
    delay(500);
    Serial.print(".");
    if (i > 60) ESP.restart();
  }
  Serial.printf("\nIP: http://%s   (stream: http://%s:81/stream)\n", WiFi.localIP().toString().c_str(),
                WiFi.localIP().toString().c_str());
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
