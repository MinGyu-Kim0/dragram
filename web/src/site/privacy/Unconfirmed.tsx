/** 운영자가 확인하기 전인 값의 자리. 그럴듯한 값으로 채우지 않고 게시 전에 눈에 띄게 둔다(#237). */
export function Unconfirmed({ what }: { what: string }) {
  return <mark className="unconfirmed">확인 필요: {what}</mark>;
}
