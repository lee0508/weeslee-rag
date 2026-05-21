// admin.html 실서버 브라우저 동작을 Playwright로 검증하는 테스트
import { test, expect } from '@playwright/test';

const ADMIN_URL =
  process.env.WEESLEE_RAG_ADMIN_URL ||
  'https://server.weeslee.co.kr/weeslee-rag/frontend/admin.html';
const ADMIN_USER = process.env.WEESLEE_RAG_ADMIN_USER;
const ADMIN_PASSWORD = process.env.WEESLEE_RAG_ADMIN_PASSWORD;

test('로그인 토큰이 없으면 로그인 오버레이를 표시한다', async ({ page }) => {
  await page.goto(ADMIN_URL, { waitUntil: 'domcontentloaded' });

  await expect(page.locator('#loginOverlay')).toBeVisible();
  await expect(page.getByText('관리자 계정으로 로그인하세요.')).toBeVisible();
});

test('실서버 Wizard 화면에 최근 실행 요약 카드가 보인다', async ({ page }) => {
  test.skip(
    !ADMIN_USER || !ADMIN_PASSWORD,
    'WEESLEE_RAG_ADMIN_USER 및 WEESLEE_RAG_ADMIN_PASSWORD가 없어서 로그인 검증을 건너뜁니다.',
  );

  await page.goto(ADMIN_URL, { waitUntil: 'domcontentloaded' });

  await page.locator('#loginUsername').fill(ADMIN_USER);
  await page.locator('#loginPassword').fill(ADMIN_PASSWORD);
  await page.locator('#loginBtn').click();

  await expect(page.locator('#loginOverlay')).toBeHidden({ timeout: 15000 });
  await expect(page.getByRole('button', { name: /Dataset Builder/ })).toBeVisible({ timeout: 15000 });

  await page.getByRole('button', { name: /Dataset Builder/ }).click();

  await expect(page.locator('#wizardResultSummary')).toBeVisible();
  await expect(page.locator('#wizardResultSummary')).toHaveText('아직 실행한 단계가 없습니다.');
  await expect(page.locator('#wizardResultStamp')).toBeVisible();
});
