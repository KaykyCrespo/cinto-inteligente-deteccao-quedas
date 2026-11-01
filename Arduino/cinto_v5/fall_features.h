/*
 * fall_features.h  -  features de janela para detecção de queda (cinto ESP32-C3)
 *
 * Mesmas contas de features.py (referência em Python). Não altere um sem o outro.
 *
 * Uso no cinto (a cada 20 ms, ou seja 50 Hz):
 *     ff_push(ax_g, ay_g, az_g, gx_dps, gy_dps, gz_dps);
 *     if (ff_ready()) {            // verdadeiro a cada 25 amostras (0,5 s)
 *         int16_t f[FF_NFEAT];
 *         ff_compute(f);           // 8 features já escaladas para int16
 *         ... montar pacote BLE versão 3 com f[] ...
 *     }
 */
#pragma once
#include <stdint.h>
#include <math.h>

#define FF_FS     50
#define FF_WIN    125
#define FF_STEP   25
#define FF_SEG    25
#define FF_NFEAT  8

static const float FF_SCALE[FF_NFEAT] = {1000.f, 1000.f, 1000.f, 5.f, 5.f, 100.f, 10.f, 1000.f};

static float ff_acc[FF_WIN][3];
static float ff_gyr[FF_WIN][3];
static int   ff_head = 0;      /* próxima posição a escrever */
static int   ff_count = 0;     /* amostras recebidas (satura em FF_WIN) */
static int   ff_since = 0;     /* amostras desde a última janela */

static inline void ff_push(float ax, float ay, float az, float gx, float gy, float gz) {
    ff_acc[ff_head][0] = ax; ff_acc[ff_head][1] = ay; ff_acc[ff_head][2] = az;
    ff_gyr[ff_head][0] = gx; ff_gyr[ff_head][1] = gy; ff_gyr[ff_head][2] = gz;
    ff_head = (ff_head + 1) % FF_WIN;
    if (ff_count < FF_WIN) ff_count++;
    ff_since++;
}

static inline int ff_ready(void) {
    if (ff_count >= FF_WIN && ff_since >= FF_STEP) { ff_since = 0; return 1; }
    return 0;
}

static inline int16_t ff_q(float v, float s) {
    float r = roundf(v * s);
    if (r > 32767.f) r = 32767.f;
    if (r < -32768.f) r = -32768.f;
    return (int16_t)r;
}

/* Calcula as features da janela mais recente (ordem cronológica a partir de ff_head). */
static inline void ff_compute_float(float out[FF_NFEAT]) {
    float am[FF_WIN];
    float amax = -1e9f, amin = 1e9f, gmax = -1e9f, jerk = 0.f;
    double sa = 0, sa2 = 0, sg = 0, sg2 = 0, sp = 0, sp2 = 0;
    float u[3] = {0, 0, 0}, v[3] = {0, 0, 0};

    for (int i = 0; i < FF_WIN; i++) {
        int k = (ff_head + i) % FF_WIN;
        const float *a = ff_acc[k], *g = ff_gyr[k];
        float m  = sqrtf(a[0] * a[0] + a[1] * a[1] + a[2] * a[2]);
        float gm = sqrtf(g[0] * g[0] + g[1] * g[1] + g[2] * g[2]);
        am[i] = m;
        if (m > amax) amax = m;
        if (m < amin) amin = m;
        if (gm > gmax) gmax = gm;
        sa += m; sa2 += (double)m * m;
        sg += gm; sg2 += (double)gm * gm;
        if (i > 0) { float d = fabsf(m - am[i - 1]); if (d > jerk) jerk = d; }
        if (i < FF_SEG)          for (int j = 0; j < 3; j++) u[j] += a[j];
        if (i >= FF_WIN - FF_SEG) { for (int j = 0; j < 3; j++) v[j] += a[j];
                                    sp += m; sp2 += (double)m * m; }
    }
    double n = FF_WIN, ns = FF_SEG;
    double ma = sa / n, mg = sg / n, mp = sp / ns;
    float astd = (float)sqrt(fmax(sa2 / n - ma * ma, 0.0));
    float gstd = (float)sqrt(fmax(sg2 / n - mg * mg, 0.0));
    float pstd = (float)sqrt(fmax(sp2 / ns - mp * mp, 0.0));

    float dot = u[0] * v[0] + u[1] * v[1] + u[2] * v[2];
    float nu = sqrtf(u[0] * u[0] + u[1] * u[1] + u[2] * u[2]);
    float nv = sqrtf(v[0] * v[0] + v[1] * v[1] + v[2] * v[2]);
    float c = dot / (nu * nv + 1e-9f);
    if (c > 1.f) c = 1.f;
    if (c < -1.f) c = -1.f;
    float tilt = acosf(c) * 57.29577951f;

    out[0] = amax; out[1] = amin; out[2] = astd; out[3] = gmax;
    out[4] = gstd; out[5] = tilt; out[6] = jerk * FF_FS; out[7] = pstd;
}

static inline void ff_compute(int16_t out[FF_NFEAT]) {
    float f[FF_NFEAT];
    ff_compute_float(f);
    for (int i = 0; i < FF_NFEAT; i++) out[i] = ff_q(f[i], FF_SCALE[i]);
}

/*
 * Pacote BLE versão 3 (24 bytes no Manufacturer Data, após o Company ID 0xFFFF):
 *   0  5B magic "OQPNB"
 *   5  1B versao = 3
 *   6  1B beltNum
 *   7  1B winSeq   (contador de janelas 0..255; o PC descarta repetidos)
 *   8 16B 8 x int16 little-endian: amax amin astd gmax gstd tilt jerk post_std
 */
static inline void ff_build_packet(uint8_t pkt[24], uint8_t beltNum, uint8_t winSeq,
                                   const int16_t f[FF_NFEAT]) {
    const char *m = "OQPNB";
    for (int i = 0; i < 5; i++) pkt[i] = (uint8_t)m[i];
    pkt[5] = 3; pkt[6] = beltNum; pkt[7] = winSeq;
    for (int i = 0; i < FF_NFEAT; i++) {
        pkt[8 + 2 * i]     = (uint8_t)(f[i] & 0xFF);
        pkt[8 + 2 * i + 1] = (uint8_t)((f[i] >> 8) & 0xFF);
    }
}
